# P2-6: Web Client (PWA) — Design Doc

**Status:** Design (não implementado)
**Prioridade:** Baixa (após federação e E2E)
**Estimativa:** 6-8 semanas de desenvolvimento dedicado

## Objetivo

Construir um cliente Web para ChatPy, permitindo que usuários entrem no
chat direto do browser sem instalar nada. Realiza a promessa de
"qualquer um pode usar" — hoje só há cliente Desktop (precisa Python) e
CLI (precisa terminal). Web broadens o alcance massivamente.

## Decisões de design

### Stack tecnológica

- **Framework:** Next.js 14+ (React 18) com TypeScript.
  - Razão: SSR para carregamento rápido, App Router para organização,
    ecosystem maduro, fácil deploy em Vercel/Netlify/self-hosted.
- **State management:** Zustand (mais leve que Redux, suficiente).
- **UI components:** shadcn/ui + Tailwind CSS (consistente com visual
  retrô do projeto via customização).
- **WebSocket:** `ws` nativo do browser (sem libs adicionais).
- **HTTP client:** `fetch` nativo + `swr` para caching.
- **Build:** Vite (via Next.js) → output estático deployável em qualquer
  CDN ou servidor estático (nginx, caddy, github pages).

### Visual

Manter o visual retrô escuro do projeto:
- Cores: `bg_main: #0a0a0a`, `text_main: #e0e0e0`, `accent: #00ff00`.
- Fonte: monospace (JetBrains Mono ou Fira Code) com fallback system.
- Sem cantos arredondados (estilo terminal/IRC clássico).
- Layout: mesmo padrão do Desktop — sidebar esquerda (salas/DMs),
  chat central, sidebar direita (membros).

### PWA (Progressive Web App)

- `manifest.json` para instalação no desktop/mobile.
- Service Worker para:
  - Cache offline de assets estáticos.
  - Push notifications (via Push API + VAPID keys).
  - Background sync de mensagens pendentes quando reconectar.
- Ícone: assets/icon-192.png, icon-512.png (gerar do ícone do projeto).

### Paridade de features com Desktop

Mantém **~95% das features** do Desktop:
- Login/registro/guest mode (P2-2)
- Salas: join/leave/create/explore/admin (promote/demote/kick/ban)
- DMs: iniciar, enviar, anexos (com preview de imagem)
- Amizades: request/accept/reject/remove/block/unblock
- Anexos: upload/download (com allowlist client-side — P0-2)
- Status: online/away/offline
- Tab-completion de @nicks (P1-1)
- Badges de não-lidas (P1-2)
- Indicador "digitando..." (P1-3)
- Themes: dark/light
- Atalhos de teclado: Ctrl+Tab, Ctrl+W, F1, Ctrl+K

**Limitações aceitáveis** (fora do escopo do Web):
- Tray icon: navegador não tem bandeja do sistema. Substituir por
  notificações nativas do browser (Notification API).
- Persistence de geometria: localStorage substitui QSettings.
- Empacotamento como .exe/.app: irrelevante (já é web).

### Arquitetura

```
chatpy-web/
├── app/
│   ├── layout.tsx           # Root layout (theme provider, fonts)
│   ├── page.tsx             # Login page
│   ├── chat/
│   │   ├── layout.tsx       # Chat shell (sidebar + main + members)
│   │   └── page.tsx         # Main chat interface
│   └── api/                 # Apenas para development proxy
├── components/
│   ├── ui/                  # shadcn/ui components
│   ├── chat/
│   │   ├── chat-tabs.tsx
│   │   ├── message-input.tsx
│   │   ├── message-list.tsx
│   │   ├── attachment-preview.tsx
│   │   └── typing-indicator.tsx
│   ├── rooms/
│   │   ├── room-list.tsx
│   │   ├── join-room-dialog.tsx
│   │   └── admin-room-dialog.tsx
│   ├── friends/
│   │   ├── friend-list.tsx
│   │   └── notifications-dialog.tsx
│   └── layout/
│       ├── sidebar.tsx
│       └── members-panel.tsx
├── lib/
│   ├── api.ts               # HTTP client (gerado de shared/protocol via quicktype)
│   ├── websocket.ts         # WebSocket client (port de shared/client/websocket.py)
│   ├── state.ts             # Zustand store (port de ClientState)
│   └── theme.ts             # Theme manager
├── public/
│   ├── manifest.json
│   ├── sw.js                # Service Worker
│   └── icons/
└── package.json
```

### Geração de tipos a partir do shared/protocol

Os schemas Pydantic em `shared/protocol/` são a fonte autoritativa de
tipos. Gerar tipos TypeScript via `quicktype`:

```bash
quicktype shared/protocol/client_events.py --lang typescript \
  -o chatpy-web/lib/types/client-events.ts
quicktype shared/protocol/server_events.py --lang typescript \
  -o chatpy-web/lib/types/server-events.ts
```

Isso garante que servidor e web client concordem sobre os payloads.

### Service Worker — push notifications

```javascript
// sw.js (esqueleto)
self.addEventListener('push', (event) => {
  const data = event.data.json();
  // { title, body, tab_name }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/icons/icon-192.png',
      badge: '/icons/badge-72.png',
      tag: data.tab_name,  // substitui notificação anterior da mesma aba
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  // Foca a janela do chat ou abre
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then(clientList => {
      if (clientList.length > 0) {
        return clientList[0].focus();
      }
      return clients.openApp('/');
    })
  );
});
```

Servidor precisa adicionar endpoint `POST /api/push/subscribe` para
registrar subscriptions VAPID e enviar pushes via `web-push` library.

### Federated login (quando P2-1 federation estiver pronto)

Suporte a login federado: usuário digita `@user@outro-servidor.com` na
tela de login → web client faz fetch `https://outro-servidor.com/.well-known/chatpy.json`
→ descobre URL base → faz login lá. Servidor local atua como proxy de
WebSocket para o servidor remoto (ou cliente conecta direto).

### Deploy

- **Vercel/Netlify:** build estático via `next build && next export`,
  deploy automático via GitHub. CDN global.
- **Self-hosted:** nginx servindo `out/` diretamente. Sem dependências
  de runtime no servidor (só estáticos).
- **Docker:** imagem alpine com nginx + arquivos estáticos, ~30 MB.

### Mobile responsiveness

Layout adapta para mobile (< 768px):
- Sidebar vira drawer (hamburger menu).
- Painel de membros esconde-se atrás de toggle.
- Input de mensagem fica fixo no bottom.
- Tabs viram horizontal scroll.

### Limitações e trade-offs

- **Sem E2E encryption no browser (inicialmente):** E2E com Signal
  Protocol no browser é possível (libsignal-js existe) mas complexo.
  Deixar para depois do E2E no Desktop (P2-3) estar consolidado.
- **Performance:** para conversas com 10k+ mensagens, virtual scrolling
  obrigatório (`react-window` ou `@tanstack/react-virtual`).
- **Tamanho do bundle:** PySide6 era ~150MB no Desktop. No Web, bundle
  inicial deve ficar ~200-300 KB gzipped.

### Plano de implementação

1. **Semana 1-2:** Setup Next.js + Tailwind + shadcn/ui. Layout shell
   (sidebar + main). Tela de login funcional.
2. **Semana 3-4:** WebSocket client (port de `shared/client/websocket.py`).
   State management. Salas: join/leave/send.
3. **Semana 5:** DMs, amizades, anexos, status.
4. **Semana 6:** PWA (manifest, service worker, push notifications).
   Mobile responsive.
5. **Semana 7:** Tab-completion, typing indicator, badges não-lidas.
6. **Semana 8:** Testes E2E (Playwright), deploy CI/CD.

### Integração com CI/CD existente

Adicionar job no `.github/workflows/ci.yml`:
```yaml
  web-build:
    name: Web Build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install deps
        working-directory: chatpy-web
        run: npm ci
      - name: Build
        working-directory: chatpy-web
        run: npm run build
      - name: Lint
        working-directory: chatpy-web
        run: npm run lint
```
