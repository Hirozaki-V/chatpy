import asyncio
import sys
import os
import logging
from chat_engine import ChatEngine

# Desabilitar logs na tela para manter o terminal limpo
logging.getLogger().handlers = []
logging.basicConfig(level=logging.ERROR)

async def obter_input(prompt):
    return await asyncio.to_thread(input, prompt)

class CLIClient:
    def __init__(self):
        self.engine = ChatEngine()
        self.auth_future = None
        self.conn_future = None
        
        # Registrar callbacks do ChatEngine
        self.engine.registrar_callback("on_connection_status", self.on_connection_status)
        self.engine.registrar_callback("on_auth_response", self.on_auth_response)
        self.engine.registrar_callback("on_chat_message", self.on_chat_message)
        self.engine.registrar_callback("on_private_message", self.on_private_message)

    def on_connection_status(self, connected):
        if self.conn_future and not self.conn_future.done():
            self.conn_future.set_result(connected)
        if not connected:
            print("\n[AVISO] Conexão perdida com o servidor.")

    def on_auth_response(self, dados):
        if self.auth_future and not self.auth_future.done():
            self.auth_future.set_result(dados)

    def on_chat_message(self, dados):
        room = dados.get("room")
        sender = dados.get("sender")
        content = dados.get("content")
        ts = dados.get("timestamp", "")
        ts_str = f"[{ts}] " if ts else ""
        
        # Exibe mensagens se forem da sala atual
        if room == self.engine.sala_atual:
            if dados.get("is_system"):
                print(f"\n{ts_str}* {content}")
            else:
                badge = dados.get("badge", "")
                badge_str = f" [{badge}]" if badge else ""
                print(f"\n{ts_str}<{sender}{badge_str}>: {content}")

    def on_private_message(self, dados):
        from_u = dados.get("from")
        to_u = dados.get("to")
        content = dados.get("content")
        ts = dados.get("timestamp", "")
        ts_str = f"[{ts}] " if ts else ""
        
        if from_u == self.engine.usuario_atual:
            print(f"\n{ts_str}* [Privado para {to_u}]: {content}")
        else:
            print(f"\n{ts_str}* [Privado de {from_u}]: {content}")

    async def iniciar(self):
        print("=========================================")
        print("          ChatPy - Terminal CLI          ")
        print("=========================================")
        
        ip = await obter_input("IP do Servidor [127.0.0.1]: ")
        ip = ip.strip() if ip.strip() else "127.0.0.1"
        
        porta_str = await obter_input("Porta [5000]: ")
        try:
            porta = int(porta_str.strip()) if porta_str.strip() else 5000
        except ValueError:
            porta = 5000

        self.conn_future = asyncio.get_running_loop().create_future()
        print(f"\nConectando a wss://{ip}:{porta} com TLS...")
        
        success = await self.engine.conectar(ip, porta)
        if not success:
            print("[ERRO] Falha de conexão. Verifique se o servidor está ativo.")
            return

        connected = await self.conn_future
        if not connected:
            print("[ERRO] Falha de conexão durante o handshake SSL.")
            return

        print("[OK] Conectado!")
        
        # Autenticação
        authenticated = False
        while not authenticated:
            print("\n1. Fazer Login")
            print("2. Registrar nova conta")
            print("3. Sair")
            opcao = await obter_input("Escolha uma opção: ")
            
            if opcao == "1":
                user = await obter_input("Nome de Usuário: ")
                pwd = await obter_input("Senha: ")
                self.auth_future = asyncio.get_running_loop().create_future()
                await self.engine.login(user, pwd)
                res = await self.auth_future
                if res.get("status") == "success":
                    authenticated = True
                    print(f"\n[OK] Autenticado como '{user}'!")
                else:
                    print(f"[ERRO] Erro de Login: {res.get('message')}")
            elif opcao == "2":
                user = await obter_input("Novo Usuário: ")
                pwd = await obter_input("Senha: ")
                self.auth_future = asyncio.get_running_loop().create_future()
                await self.engine.registrar(user, pwd)
                res = await self.auth_future
                if res.get("status") == "success":
                    print(f"[OK] Conta '{user}' criada com sucesso! Faça login agora.")
                else:
                    print(f"[ERRO] Erro ao Registrar: {res.get('message')}")
            elif opcao == "3":
                print("Saindo...")
                return
            else:
                print("Opção inválida.")

        # Loop principal de chat
        print(f"\nVocê entrou na sala '{self.engine.sala_atual}'.")
        print("Comandos disponíveis:")
        print("  /msg <usuario> <texto> - Enviar mensagem privada")
        print("  /chamar <usuario>      - Chamar a atenção de um usuário")
        print("  /friend add <usuario>  - Adicionar amigo")
        print("  /friend remove <user>  - Remover amigo")
        print("  /kick <usuario>        - Expulsar da sala")
        print("  /ban <usuario>         - Banir da sala")
        print("  /sair                  - Sair do chat")
        print("  /help                  - Ajuda com comandos extras")
        print("Digite sua mensagem e aperte Enter:")

        while self.engine.running:
            try:
                linha = await obter_input("")
                linha = linha.strip()
                if not linha:
                    continue
                
                if linha == "/sair":
                    self.engine.running = False
                    break
                
                if linha.startswith("/friend add "):
                    dest = linha[len("/friend add "):].strip()
                    await self.engine.friend_action("add", dest)
                elif linha.startswith("/friend remove "):
                    dest = linha[len("/friend remove "):].strip()
                    await self.engine.friend_action("remove", dest)
                elif linha.startswith("/kick "):
                    dest = linha[len("/kick "):].strip()
                    await self.engine.moderation_action("kick", dest, self.engine.sala_atual)
                elif linha.startswith("/ban "):
                    dest = linha[len("/ban "):].strip()
                    await self.engine.moderation_action("ban", dest, self.engine.sala_atual)
                elif linha.startswith("/chamar "):
                    dest = linha[len("/chamar "):].strip()
                    await self.engine.enviar_json({"type": "nudge", "room": self.engine.sala_atual, "target": dest})
                elif linha == "/chamar":
                    await self.engine.enviar_json({"type": "nudge", "room": self.engine.sala_atual})
                elif linha == "/help":
                    await self.engine.enviar_json({"type": "help", "room": self.engine.sala_atual})
                else:
                    # Enviar mensagem pública (ou DM se for comando /msg no engine)
                    await self.engine.enviar_mensagem(self.engine.sala_atual, linha)
            except (KeyboardInterrupt, EOFError):
                break

        print("\nSaindo do ChatPy CLI. Até logo!")

if __name__ == "__main__":
    client = CLIClient()
    try:
        asyncio.run(client.iniciar())
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
