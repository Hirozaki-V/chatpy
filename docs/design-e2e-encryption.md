# P2-3: E2E Encryption para DMs — Design Doc

**Status:** Design (não implementado)
**Prioridade:** Média
**Estimativa:** 4-6 semanas de desenvolvimento dedicado

## Objetivo

Cifrar mensagens de DM (Direct Message) de ponta a ponta entre os dois
participantes, de forma que o servidor não consiga ler o conteúdo.
Isso realiza a promessa de "seguro" do projeto — hoje as DMs são
armazenadas em texto plano no banco do servidor.

## Decisões de design

### Algoritmo: Signal Protocol (Double Ratchet)

Implementar o **Double Ratchet** (mesmo usado por Signal, WhatsApp,
Matrix/Pantalaimon). Combina:

- **X3DH (Extended Triple Diffie-Hellman)**: handshake inicial para
  estabelecer chave compartilhada entre dois dispositivos.
- **Double Ratchet**: deriva novas chaves a cada mensagem, oferecendo
  forward secrecy (comprometimento de chave atual não decripta mensagens
  anteriores) e post-compromise security (comprometimento temporário
  se recupera após algumas mensagens).

**Alternativas consideradas:**
- PGP simples: sem forward secrecy, complexo para usuários leigos.
- AES-GCM com chave fixa por par: sem forward secrecy.
- MLS (Messaging Layer Security): mais moderno, mas mais complexo e
  voltado para grupos grandes (overkill para 1:1 DMs).

### Bibliotecas

- **Python (server + clientes):** `python-axolotl` (port da libsignal) ou
  `cryptography` (manual, mais controle).
- **Cliente Web (futuro P2-6):** `libsignal` (JavaScript) ou `window.crypto.subtle`.

### Key management

- **Identity Key:** par Ed25519 por usuário, gerado no primeiro login,
  persistido localmente (não no servidor). A chave pública é publicada
  no perfil do usuário (servidor armazena só a pública).
- **PreKeys (One-Time):** pool de chaves Efêmeras pré-carregadas no
  servidor. Outro usuário pegará uma para iniciar conversa.
- **Signed PreKey:** uma chave efêmera rotacionada periodicamente
  (semanal), assinada pela Identity Key.

### Fluxo de DM E2E

1. Alice quer mandar DM para Bob (que ela ainda não conversou).
2. Alice busca no servidor: `GET /api/users/bob/prekey` → recebe
   Bob's Identity Key + Signed PreKey + One-Time PreKey.
3. Alice executa X3DH localmente → deriva chave compartilhada `RK`.
4. Alice inicializa Double Ratchet sender com `RK`.
5. Alice cifra mensagem com AES-256-GCM usando chave derivada.
6. Alice envia: `POST /api/dm/send` com `{ciphertext, header (ratchet_step)}`.
7. Servidor armazena ciphertext + header (não consegue decifrar).
8. Bob recebe via WebSocket: `{ciphertext, header}`.
9. Bob executa X3DH localmente com sua Identity Key → mesma `RK`.
10. Bob inicializa Double Ratchet receiver com `RK`.
11. Bob decifra com AES-256-GCM.

### Mudanças no schema

```sql
-- Tabela: user_identity_keys
CREATE TABLE user_identity_keys (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    public_key_pem TEXT NOT NULL,        -- Identity Key pública
    signed_prekey_pem TEXT NOT NULL,     -- Signed PreKey atual
    signed_prekey_sig TEXT NOT NULL,     -- Assinatura da Signed PreKey
    signed_prekey_rotated_at TIMESTAMP NOT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Tabela: one_time_prekeys (pool)
CREATE TABLE one_time_prekeys (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key_id INTEGER NOT NULL,             -- ID sequencial
    public_key_pem TEXT NOT NULL,
    used BOOLEAN DEFAULT FALSE,          -- True quando consumida em X3DH
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, key_id)
);

-- Tabela: encrypted_messages (substitui private_messages para DMs E2E)
CREATE TABLE encrypted_messages (
    id UUID PRIMARY KEY,
    sender_id UUID REFERENCES users(id),
    receiver_id UUID REFERENCES users(id),
    ciphertext BLOB NOT NULL,            -- AES-256-GCM ciphertext
    header JSON NOT NULL,                -- {ratchet_step, dh_pub}
    timestamp TIMESTAMP NOT NULL,
    -- attachment_id ainda pode existir mas o attachment também deve ser
    -- cifrado (AES-256-GCM com chave separada derivada do ratchet)
);
```

### Mudanças no protocolo WebSocket

Novo evento `message.send_private_e2e`:
```json
{
  "event": "message.send_private_e2e",
  "payload": {
    "receiver_id": "uuid",
    "ciphertext": "base64...",
    "header": {"ratchet_step": 1, "dh_pub": "base64..."},
    "attachment_ciphertext": "base64...",  // opcional
    "attachment_header": {...}
  }
}
```

Servidor só retransmite o payload sem inspecionar `ciphertext`.

### Backward compatibility

- Manter `message.send_private` (DMs não-E2E) para usuários que optarem
  por não usar E2E (ex: servidor single-admin, sem necessidade).
- Cliente indica visualmente: 🔒 para DMs E2E, 🔓 para DMs plain.
- Migration tool: DMs plain antigas NÃO podem ser retroativamente
  cifradas (servidor não tem as chaves) — ficam marcadas como "histórico
  não-E2E" no topo da conversa.

### Limitações conhecidas

- **Multi-device:** se Alice loga em 2 dispositivos, ambos precisam
  derivar a mesma chave. Solução: cada dispositivo tem sua Identity Key,
  e a sessão E2E é estabelecida por dispositivo (não por usuário). Isso
  significa que Bob precisa de uma sessão E2E separada com cada
  dispositivo de Alice. Complexo mas necessário.
- **Group DMs:** Double Ratchet é 1:1. Para DMs em grupo (3+ pessoas),
  usar MLS ou Sender Key (subprotocolo do Signal). Fora do escopo inicial.
- **Verification:** usuários precisam verificar Safety Numbers (指纹) fora
  de banda (ex: ler código em voz alta) para confirmar que não há
  Man-in-the-Middle. UX challenge.
- **Key backup:** se o usuário perde o dispositivo, perde o acesso a
  histórico E2E. Solução: Key Backup Service (como Signal) — fora do
  escopo inicial.

### Plano de implementação

1. **Semana 1-2:** Schema + endpoints REST para PreKey management
   (`POST /api/keys/identity`, `POST /api/keys/prekeys`, `GET /api/users/{id}/prekey`).
2. **Semana 3-4:** Implementar X3DH + Double Ratchet em biblioteca
   compartilhada (`shared/e2e/`).
3. **Semana 5:** Integrar no cliente Desktop (UI para ativar E2E por DM).
4. **Semana 6:** Integrar no cliente CLI. Testes E2E completos.
5. **Semana 7+:** Multi-device, key backup, verification UX.

### Riscos

- **Bug de criptografia = vulnerabilidade silenciosa.** Mitigação: usar
  biblioteca auditada (python-axolotl), não rolar cripto própria.
- **UX complexa** pode afastar usuários não-técnicos. Mitigação: E2E
  opt-in por DM, com toggle claro na UI.
- **Compatibilidade federada (P2-1):** DMs E2E entre servidores federados
  funciona naturalmente (a cifragem é client-to-client, o servidor só
  retransmite), MAS o handshake X3DH precisa buscar PreKeys no servidor
  remoto. Requer endpoint federado `GET /api/federation/users/{id}/prekey`.
