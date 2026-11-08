"""Exercise actual HTTP/1.1 keep-alive across a human-sized pause, without any cloud call."""
import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from pydantic import SecretStr

from shinar.providers.openai_compatible import OpenAICompatibleLLMProvider, OpenAICompatibleLLMSettings


def test_role_connections_are_isolated_and_dialogue_survives_a_six_second_pause(monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1')
    peer_ports = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            peer_ports.append(self.client_address[1])
            body = json.dumps({'id': 'local-test', 'object': 'chat.completion', 'created': 0,
                'model': 'local-test', 'choices': [{'index': 0, 'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': 'A complete reply.'}}],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def run():
        provider = OpenAICompatibleLLMProvider(OpenAICompatibleLLMSettings(api_key=SecretStr('local-only'),
            base_url=f'http://127.0.0.1:{server.server_port}/v1', reasoning_model='reasoner', dialogue_model='dialogue'))
        try:
            await provider._invoke_text(provider._reasoning_client, [])
            await provider._invoke_text(provider._dialogue_client, [])
            await asyncio.sleep(5.2)  # Longer than HTTPX's default expiry.
            await provider._invoke_text(provider._dialogue_client, [])
            assert len(peer_ports) == 3
            assert peer_ports[0] != peer_ports[1]  # Speculation cannot occupy this socket.
            assert peer_ports[1] == peer_ports[2]  # No fresh TCP handshake on the next turn.
        finally:
            await provider.aclose()
        assert all(client.is_closed for client in provider._http_async_clients.values())

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
