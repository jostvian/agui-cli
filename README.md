# agui-cli

Cliente de línea de comandos para conectarse a un servidor **ag-ui** ya publicado.

## Requisitos

- Python 3.10 o superior (no se requieren dependencias externas).
- Variable de entorno `AG_UI_SERVER` con la URL completa del endpoint del servidor
  (por ejemplo, `https://tu-servidor.agui/api/clients` o `wss://tu-servidor.agui/ws`).

## Uso

1. Asegura que `AG_UI_SERVER` esté definida o pasa la URL con `--server`.
2. Ejecuta el CLI y escribe la pregunta que deseas enviar al agente. El cliente
   mostrará en tiempo real cada mensaje de usuario que llegue desde el servidor.

```bash
python -m agui_cli.cli "¿Quién se ha conectado?"

# o bien
AG_UI_SERVER="https://servidor.agui/stream" python -m agui_cli.cli
```

### Argumentos

- `question`: Pregunta a enviar al agente. Si se omite, el programa pedirá la
  entrada de manera interactiva.
- `--server`: URL del servidor ag-ui. Si no se proporciona, se usa el valor de
  `AG_UI_SERVER`.
- `--timeout`: Tiempo máximo de espera para conexiones en segundos (por defecto 10).

## Notas de implementación

- El cliente soporta endpoints HTTP(S) que emiten Server-Sent Events o JSON
  delimitado por líneas y endpoints WebSocket utilizando el protocolo ag-ui.
- Los mensajes recibidos se normalizan mostrando prefijos comunes (`user`,
  `sender`, `name`, `role`) para facilitar la lectura en terminal.
