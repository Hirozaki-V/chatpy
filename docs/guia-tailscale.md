# Guia: Acesso Remoto com Tailscale

Tailscale é uma VPN moderna que cria uma rede privada entre seus dispositivos — sem precisar configurar port forwarding, DNS ou TLS. É a forma mais simples e segura de acessar seu servidor ChatPy de qualquer lugar.

---

## Por que Tailscale?

- **Sem port forwarding**: não precisa mexer no roteador
- **Criptografado ponta a ponta**: tráfego não passa por servidores intermediários
- **Gratuito para uso pessoal**: até 100 dispositivos
- **Sem IP público exposto**: seu servidor não fica visível para a internet
- **Funciona atrás de NAT**: não importa que rede você está

---

## Passo a passo

### 1. Instalar Tailscale no servidor

No computador/Raspberry Pi onde o ChatPy está rodando:

```bash
# Linux
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Anote o IP que aparece (ex: 100.64.1.25)
tailscale ip -4
```

### 2. Instalar Tailscale no cliente

No computador de onde você vai acessar o chat:

- **Windows/Mac**: baixe em [tailscale.com/download](https://tailscale.com/download)
- **Linux**: mesmo comando do passo 1
- **Mobile**: app Tailscale na Play Store / App Store

Faça login com a **mesma conta** do passo 1.

### 3. Conectar o cliente ao servidor

Agora seus dois computadores estão na mesma rede virtual. Use o IP do Tailscale (100.x.x.x):

```bash
# CLI
python client-cli/main.py --host 100.64.1.25 --port 5000

# Desktop
# Campo "Servidor": 100.64.1.25:5000
```

Pronto! Você está acessando seu chat de qualquer lugar do mundo, de forma criptografada, sem expor portas.

---

## Compartilhar com amigos

Para que outras pessoas acessem seu servidor ChatPy via Tailscale:

1. No painel do Tailscale (admin.tailscale.com), vá em **Users**
2. Adicione o email do amigo
3. Ele instala Tailscale e faz login
4. Ele usa o IP do seu servidor (100.x.x.x) no cliente ChatPy

Alternativamente, use **Tailscale Funnel** para expor o servidor publicamente (com HTTPS automático):

```bash
sudo tailscale funnel 5000
```

Isso gera uma URL pública como `https://seu-pi.tailnet-abc.ts.net` — qualquer pessoa pode acessar, mesmo sem Tailscale.

---

## Vantagens vs port forwarding tradicional

| Aspecto | Port Forwarding | Tailscale |
|---|---|---|
| Configuração no roteador | Necessária | Não precisa |
| Segurança | IP exposto à internet | Rede privada criptografada |
| HTTPS | Precisa configurar (Caddy/certbot) | Automático (com Funnel) |
| Mudança de IP | Precisa de DNS dinâmico | IP fixo 100.x.x.x |
| Funciona atrás de NAT corporativa | Não | Sim |
| Latência | Direta | Pode ter pequeno overhead |

---

## Troubleshooting

### "Connection refused"

Verifique se o Tailscale está rodando em ambas as máquinas:
```bash
tailscale status
```

### Não consigo pingar o IP do servidor

Verifique se ambas as máquinas estão na mesma tailnet (mesma conta Tailscale).

### Lentidão

Tailscale geralmente usa conexão direta (peer-to-peer). Se passar por relay (DERP), pode haver latência. Verifique:
```bash
tailscale status
# Procure por "direct" ou "relay" na coluna de conexão
```
