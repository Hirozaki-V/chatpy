# Guia de Hospedagem no Raspberry Pi (V1)

Este guia ensina a realizar a hospedagem e a otimização do servidor **ChatPy V2** em placas Raspberry Pi (modelos 3B, 4, 5 ou superiores) executando o Raspberry Pi OS (64-bit).

---

## 📋 Pré-requisitos

1. Raspberry Pi configurado com acesso à rede e SSH habilitado.
2. Sistema operacional de **64 bits** (fortemente recomendado para melhor compatibilidade com pacotes Python e Docker).
3. Docker e Docker Compose instalados.

### Instalando o Docker no Raspberry Pi
Se você ainda não possui o Docker instalado, execute os seguintes comandos no terminal do seu Raspberry Pi:

```bash
# Baixa e executa o script oficial de instalação
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Adiciona seu usuário ao grupo docker para rodar sem sudo
sudo usermod -aG docker $USER
```
*Reinicie o seu terminal ou efetue logout/login para aplicar as permissões do grupo.*

---

## ⚡ Otimização de I/O (Cartão MicroSD)

Cartões MicroSD convencionais sofrem degradação rápida quando expostos a muitas operações de escrita aleatória. Por esse motivo, o ChatPy V2 utiliza a seguinte estratégia padrão:

1. **SQLite por Padrão**: Não requer um serviço pesado de banco de dados rodando em background (economizando CPU e RAM).
2. **Modo WAL (Write-Ahead Logging)**: A persistência do SQLite do ChatPy é configurada no modo WAL. As escritas são agrupadas sequencialmente em um arquivo auxiliar de log, reduzindo o desgaste físico do cartão MicroSD e melhorando o rendimento das consultas simultâneas.

---

## 🚀 Como Inicializar

No diretório raiz do projeto no seu Raspberry Pi, execute o Docker Compose para baixar a imagem base e iniciar o servidor leve:

```bash
docker compose up -d
```

### Verificando Consumo de Recursos
O ChatPy foi desenhado sob o princípio de baixo consumo (adequado para instâncias com apenas 1GB ou 2GB de RAM). Para monitorar o consumo real do container, execute:

```bash
docker stats chatpy-server
```
*Em condições normais, o uso de memória em repouso do container do servidor fica abaixo de **50MB**.*

---

## 📌 Diagnósticos e Logs

Para monitorar os logs do servidor e conexões em tempo real, use:

```bash
docker compose logs -f chatpy-server
```
