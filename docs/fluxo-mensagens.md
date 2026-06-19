# Fluxo de Mensagens

## Mensagem de sala (pública)

```
Usuário A digita mensagem →
  Cliente envia WS: message.send_room {room_id, content} →
    Servidor valida: é membro? não está banido? conteúdo válido? →
      Servidor persiste no banco (messages) →
        Servidor busca membros da sala →
          Servidor envia WS: message.receive {sender, content, timestamp} para todos os membros
```

## Mensagem privada (DM)

```
Usuário A digita DM →
  Cliente envia WS: message.send_private {receiver_id, content} →
    Servidor valida: são amigos? não há bloqueio? →
      Servidor persiste no banco (private_messages) →
        Servidor envia WS: message.receive para o remetente E o destinatário
```

## Mensagem federada (cross-server)

```
Usuário A (servidor X) manda DM para @bob@servidor-y →
  Cliente envia WS: message.send_federated {receiver_username: "@bob@y", content} →
    Servidor X parseia: user=bob, domain=y →
      Servidor X busca peer "y" na tabela server_peers →
        Servidor X assina payload com Ed25519 →
          Servidor X envia HTTP POST para https://y/api/federation/dm →
            Servidor Y valida assinatura →
              Servidor Y persiste DM →
                Servidor Y entrega via WS ao Bob (se online) →
                  Servidor Y responde 200 OK →
                    Servidor X confirma ao remetente A via WS
```

## Presença

```
Usuário entra (WS auth.success) →
  Servidor marca user.status = "online" no banco →
    Servidor broadcast WS: user.presence {user_id, status: "online"} para todos os conectados

Usuário sai (WS disconnect) →
  Servidor marca user.status = "offline" →
    Servidor broadcast WS: user.presence {user_id, status: "offline"}
```

## Indicador "digitando..."

```
Usuário A digita →
  Cliente faz debounce de 2s →
    Cliente envia WS: user.typing {room_id ou receiver_id} →
      Servidor retransmite WS: user.typing_broadcast {username} para membros/destinatário →
        Cliente B mostra "A está digitando..." na status bar por 4s
```

## Bots

```
Usuário digita "!ping" numa sala →
  Servidor processa message.send_room normalmente →
    Após broadcast, servidor verifica se mensagem começa com "!" →
      Servidor passa para bots registrados →
        Bot processa comando e retorna resposta →
          Servidor envia resposta como message.receive para a sala
```
