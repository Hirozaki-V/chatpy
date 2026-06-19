# Guia: Raspberry Pi

O ChatPy foi projetado desde o início para rodar em Raspberry Pi. Com SQLite e ~50MB de RAM, até um Pi 3B (1GB RAM) roda sem problemas.

---

## Requisitos

- Raspberry Pi 3B, 4 ou 5 (recomendado: 4 com 2GB+)
- Cartão SD 16GB+ (Classe 10)
- Raspberry Pi OS (64-bit recomendado)
- Conexão à rede (WiFi ou cabo)

---

## Passo a passo

### 1. Instalar Docker

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Faça logout e login novamente
```

### 2. Baixar o ChatPy

```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy
```

### 3. Configurar

```bash
# Gerar chave secreta
echo "JWT_SECRET=$(openssl rand -hex 32)" > .env

# Reduzir verbosidade de logs (economiza SD card)
echo "LOG_LEVEL=WARNING" >> .env

# Ativar backup automático (salva no volume Docker)
echo "BACKUP_ENABLED=true" >> .env
echo "BACKUP_INTERVAL_HOURS=24" >> .env
echo "BACKUP_KEEP_COUNT=3" >> .env
```

### 4. Subir o servidor

```bash
docker compose up -d
```

### 5. Verificar

```bash
curl http://localhost:5000/health
```

Deve retornar `"status": "healthy"`.

### 6. Descobrir o IP do Pi na rede

```bash
hostname -I
# Exemplo: 192.168.1.50
```

### 7. Conectar de outro computador

No seu PC, instale o cliente e conecte:

```bash
# CLI
python client-cli/main.py --host 192.168.1.50 --port 5000

# Desktop
# Campo "Servidor": 192.168.1.50:5000
```

---

## Otimizações para Raspberry Pi

### Reduzir desgaste do SD card

O SQLite faz muitas escritas. Para reduzir desgaste:

```bash
# No .env, usar tmpfs para uploads temporários (opcional)
echo "UPLOAD_DIR=/tmp/chatpy-uploads" >> .env
```

### Usar disco USB em vez do SD card

Se você tem um HD/SSD USB conectado ao Pi:

```bash
# Montar o disco
sudo mount /dev/sda1 /mnt/data

# No docker-compose.yml, mudar o volume:
# chatpy-data:/mnt/data/chatpy
```

### Log para RAM (reduz escrita no SD)

Adicionar no `/etc/fstab`:
```
tmpfs /var/log tmpfs defaults,noatime,size=100M 0 0
```

---

## Acesso remoto (fora de casa)

### Opção A: Tailscale (recomendado)

Veja o [Guia Tailscale](guia-tailscale.md). Mais simples e seguro que port forwarding.

### Opção B: Port forwarding no roteador

1. Acesse o admin do roteador (geralmente `192.168.0.1`)
2. Vá em "Port Forwarding" ou "Virtual Server"
3. Adicione regra: porta externa 5000 → IP do Pi → porta 5000
4. No cliente, use seu IP público (descubra em `ifconfig.me`)

⚠️ **Atenção:** sem HTTPS, senhas viajam em texto plano. Use Tailscale ou configure Caddy/nginx com TLS.

---

## Consumo de recursos

| Recurso | Consumo típico |
|---|---|
| RAM | ~50-80 MB (SQLite, sem Redis) |
| CPU | < 5% com 10 usuários ativos |
| Disco | ~10 MB base + uploads + banco |
| Rede | ~1 KB por mensagem |

Um Pi 3B aguenta ~50 usuários simultâneos sem problemas.
