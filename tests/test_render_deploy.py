"""Testes offline da logica de publicacao no Render."""
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

ARQUIVO = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "render_deploy.py"
spec = importlib.util.spec_from_file_location("render_deploy", ARQUIVO)
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)
SHA = "a" * 40


class RenderDeployTests(unittest.TestCase):
    @patch.object(render, "urlopen")
    def test_resposta_202_sem_corpo_e_processada(self, abrir):
        resposta = abrir.return_value.__enter__.return_value
        resposta.status = 202
        resposta.read.return_value = b""
        self.assertEqual(render.requisitar_json("https://api.render.com/hook", "POST"), (202, {}))

    def test_hook_preserva_key_e_adiciona_sha(self):
        url = render.url_hook_com_commit("https://api.render.com/deploy/srv-123?key=segredo", SHA)
        self.assertEqual(url, "https://api.render.com/deploy/srv-123?key=segredo&ref=" + SHA)

    def test_rejeita_hook_sem_https(self):
        with self.assertRaises(render.DeployError):
            render.url_hook_com_commit("http://localhost:8000/hook", SHA)

    @patch.object(render, "requisitar_json", return_value=(200, {"deploy": {"id": "dep-teste123"}}))
    def test_retorna_id_do_deploy(self, requisitar):
        self.assertEqual(render.criar_deploy("https://api.render.com/hook?key=abc", SHA), "dep-teste123")
        self.assertEqual(requisitar.call_args.kwargs["method"], "POST")

    @patch.object(render, "requisitar_json", return_value=(202, {}))
    def test_rejeita_deploy_enfileirado_sem_id(self, _):
        with self.assertRaises(render.DeployError):
            render.criar_deploy("https://api.render.com/hook?key=abc", SHA)

    @patch.object(render, "consultar_deploy", side_effect=[
        {"status": "build_in_progress", "commit": {"id": SHA}},
        {"status": "live", "commit": {"id": SHA}},
    ])
    @patch.object(render.time, "sleep")
    def test_aguarda_commit_exato(self, sleep, consultar):
        render.aguardar_deploy("srv-teste", "dep-teste", "api-key", SHA, 60, 1)
        self.assertEqual(consultar.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch.object(render, "consultar_deploy", return_value={"status": "live", "commit": {"id": "b" * 40}})
    def test_rejeita_commit_errado(self, _):
        with self.assertRaises(render.DeployError):
            render.aguardar_deploy("srv-teste", "dep-teste", "api-key", SHA, 60, 1)

    @patch.object(render, "consultar_deploy", return_value={"status": "build_failed"})
    def test_rejeita_build_failed(self, _):
        with self.assertRaises(render.DeployError):
            render.aguardar_deploy("srv-teste", "dep-teste", "api-key", SHA, 60, 1)

    @patch.object(render, "requisitar_json", return_value=(200, {"status": "ok", "problemas_de_configuracao": []}))
    def test_health_aprovado(self, request):
        render.verificar_saude("https://assessoria.onrender.com", 1, 1)
        self.assertEqual(request.call_args.args[0], "https://assessoria.onrender.com/health")

    @patch.object(render, "requisitar_json", return_value=(200, {"status": "atencao", "problemas_de_configuracao": ["API_KEY"]}))
    @patch.object(render.time, "monotonic", side_effect=[0, 2])
    def test_rejeita_health_com_config_incompleta(self, _, __):
        with self.assertRaises(render.DeployError):
            render.verificar_saude("https://assessoria.onrender.com", 1, 1)


if __name__ == "__main__":
    unittest.main()
