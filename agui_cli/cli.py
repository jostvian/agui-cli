import argparse
import os
import sys
from typing import Optional

from .client import AgUIClient


def resolve_server_url(explicit: Optional[str]) -> str:
    server = explicit or os.environ.get("AG_UI_SERVER")
    if not server:
        raise SystemExit(
            "AG_UI_SERVER is not set. Provide it via --server or environment variable."
        )
    return server


def prompt_question(default: Optional[str]) -> str:
    if default:
        return default
    try:
        return input("¿Qué te gustaría preguntarle al agente? ")
    except EOFError:
        raise SystemExit("No se proporcionó una pregunta para enviar al servidor.")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Cliente CLI para ag-ui")
    parser.add_argument("question", nargs="?", help="Pregunta para enviar al servidor")
    parser.add_argument(
        "--server",
        help="URL completa del servidor ag-ui (por defecto se usa AG_UI_SERVER)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Tiempo máximo de espera para las conexiones (segundos)",
    )

    args = parser.parse_args(argv)
    server_url = resolve_server_url(args.server)
    question = prompt_question(args.question)

    client = AgUIClient(server_url, timeout=args.timeout)
    print(f"Conectando a {server_url}...\n")

    try:
        for message in client.stream(question):
            print(message.text)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    except Exception as exc:  # pragma: no cover - defensive for CLI runtime
        print(f"Error al conectar o recibir datos: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
