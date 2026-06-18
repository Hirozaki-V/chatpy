# Guia de Hospedagem Segura com Tailscale

Este guia ensina a utilizar o **Tailscale** em conjunto com o **ChatPy V2** para habilitar acesso remoto seguro e hospedagem doméstica sem a necessidade de abrir portas no roteador (port-forwarding) ou contratar IPs públicos estáticos, driblando inclusive Carrier-Grade NAT (CGNAT).

---

## 💡 Por que usar Tailscale com o ChatPy?

1. **Segurança Avançada**: O servidor ChatPy não fica exposto para a internet pública. Apenas dispositivos autorizados na sua rede mesh privada (Tailnet) podem localizá-lo e conectar.
2. **Zero Configuração de Roteador**: Não é necessário configurar regras de NAT, DMZ ou redirecionamento de portas no seu modem residencial.
3. **Magic IP Fixo**: O Tailscale atribui um endereço de IP privado na faixa `100.x.y.z` para cada dispositivo da sua rede, facilitando a configuração dos clientes.
4. **Infraestrutura Pronta para Bridge Servers**: No futuro (V3), a conexão segura entre múltiplos servidores independentes poderá ser feita de forma simples adicionando chaves de autenticação Tailscale (Authkeys) para estabelecer canais criptografados diretos P2P.

---

## 🛠️ Passo a Passo de Configuração

### 1. Criar Conta no Tailscale
Acesse [tailscale.com](https://tailscale.com) e crie uma conta gratuita (grátis para uso pessoal com até 3 usuários e 100 dispositivos).

### 2. Instalar no Servidor (Ex: Raspberry Pi ou VPS)
No terminal da máquina onde rodará o docker do ChatPy, instale o cliente executando:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

Autentique a máquina rodando:
```bash
sudo tailscale up
```
*Clique no link exibido no console para autorizar a máquina no painel administrativo do Tailscale.*

Anote o IP do dispositivo na rede Tailscale executando:
```bash
tailscale ip -4
```
*(Será um endereço semelhante a `100.101.222.40`)*

### 3. Iniciar o Servidor
Certifique-se de que o servidor ChatPy está rodando. O container expõe a porta `5000` em todas as interfaces do host (`0.0.0.0`), o que inclui automaticamente a interface de rede virtual do Tailscale:

```bash
docker compose up -d
```

### 4. Instalar o Tailscale nos Dispositivos Cliente
Instale o cliente Tailscale no seu computador pessoal ou celular:
* **Windows/macOS/Linux**: Instale o instalador nativo do site oficial e faça o login com a mesma conta.
* **Android/iOS**: Baixe na respectiva loja de aplicativos.

---

## 🔌 Conectando os Clientes ao Servidor

Ao iniciar o seu cliente desktop ou de terminal, aponte as configurações de servidor para o IP virtual do Tailscale anotado na etapa 2:

### Exemplo de Conexão no Cliente Desktop:
* **Servidor**: `100.101.222.40:5000`

### Exemplo de Conexão no Cliente CLI:
```bash
python client-cli/main.py --host 100.101.222.40 --port 5000
```

Pronto! A comunicação será 100% criptografada de ponta a ponta e trafegará de forma totalmente direta e segura pela VPN mesh do Tailscale.
