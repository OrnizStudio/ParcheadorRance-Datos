"""Fase D9: el Historial global (`historial/central/<AAAA-MM>.json`, docs/canales.md §1 y §2.2).

Al fusionar un juego nuevo, una edición nueva o un cambio en la ficha central de un canal, el robot pone como mensaje
del commit una línea `Historial-central: {…}` (`solicitudes.linea_historial`). El trabajo `publicar` la convierte en
una fila del mes, con los archivos y campos que cambió ese commit en `juegos/<juego>/`, y la deja en `main` en la misma
propuesta que el catálogo.
"""

import json
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import particion  # noqa: E402
import publicar  # noqa: E402
import solicitudes  # noqa: E402
from test_fase_d_solicitudes_programa import admin, juzgar, main_es  # noqa: E402
from test_particion import todo_el_modelo  # noqa: E402
from test_publicar import TrabajoEntero, g, sueltos_de  # noqa: E402
from permisos import Permisos, Rol  # noqa: E402
from test_sueltos import YO, Propuesta  # noqa: E402


def sol(tipo="central", canal="rance_es", juego="rance-x", directa=True):
    return solicitudes.Solicitud(tipo, canal, juego, directa)


class LineaDelHistorial(unittest.TestCase):
    def test_ida_y_vuelta(self):
        linea = solicitudes.linea_historial(sol(), "eva-trad", 7, 42)
        self.assertTrue(linea.startswith("Historial-central: {"))
        self.assertNotIn("\n", linea)
        self.assertEqual({"canal": "rance_es", "cuenta": "eva-trad", "cuentaId": 7, "tipo": "central",
                          "juego": "rance-x", "directa": True, "propuesta": 42}, publicar.fila_de_la_linea(linea))

    def test_vale_la_ultima_y_solo_al_principio_de_linea(self):
        buena = solicitudes.linea_historial(sol(juego="otro"), "eva", 7, 5)
        mala = solicitudes.linea_historial(sol(), "suplanta", 9, 1)
        self.assertEqual("otro", publicar.fila_de_la_linea(f"Título (#5)\n\n{mala}\n{buena}\n")["juego"])
        self.assertIsNone(publicar.fila_de_la_linea(f"texto {buena}"))
        self.assertIsNone(publicar.fila_de_la_linea(""))
        self.assertIsNone(publicar.fila_de_la_linea(None))

    def test_lo_que_no_vale_no_sale(self):
        base = json.loads(solicitudes.linea_historial(sol(), "eva", 7, 42)[len(solicitudes.MARCA_HISTORIAL):])
        malos = [
            {"v": 2}, {"canal": "Rance ES"}, {"canal": "ab"}, {"canal": "x" * 21}, {"juego": "../etc"},
            {"juego": "a" * 65}, {"juego": ""}, {"cuenta": "-eva"}, {"cuenta": "e" * 40}, {"cuenta": "eva<b>"},
            {"cuentaId": "7"}, {"cuentaId": 0}, {"cuentaId": True}, {"cuentaId": 7.0}, {"propuesta": -1},
            {"propuesta": None}, {"tipo": "canal"}, {"tipo": "verificacion"}, {"directa": "si"},
        ]
        for cambio in malos:
            with self.subTest(cambio=cambio):
                texto = solicitudes.MARCA_HISTORIAL + json.dumps({**base, **cambio})
                self.assertIsNone(publicar.fila_de_la_linea(texto))
        self.assertIsNone(publicar.fila_de_la_linea(solicitudes.MARCA_HISTORIAL + "{no es json}"))
        self.assertIsNone(publicar.fila_de_la_linea(solicitudes.MARCA_HISTORIAL + "[1, 2]"))
        # Un nombre con caracteres raros nunca llega: la cuenta y el juego van validados.
        self.assertIsNone(publicar.fila_de_la_linea(solicitudes.MARCA_HISTORIAL + json.dumps({**base, "juego": "ä"})))


class NadieMasLoEscribe(unittest.TestCase):
    def test_un_canal_no_toca_el_historial(self):
        p = Propuesta(main_es(verificado=True)).poner("historial/central/2026-11.json",
                                                      {"esquema": 1, "mes": "2026-11", "filas": []})
        # Ni un Administrador de un canal verificado ni uno del canal oficial: es del Dueño (y del robot).
        self.assertTrue(juzgar(p, admin()))
        oficial = Permisos(Rol.ADMINISTRADOR, por_canal={"ornizen": Rol.ADMINISTRADOR}, cuenta_id=YO)
        motivos = juzgar(p, oficial)
        self.assertTrue(any("historial/central/2026-11.json" in m for m in motivos), motivos)


class EnElTrabajo(unittest.TestCase):
    # Lo de TrabajoEntero sin heredar sus pruebas (si no, se correrían otra vez aquí).
    setUp, tearDown, correr, del_remoto = (TrabajoEntero.setUp, TrabajoEntero.tearDown, TrabajoEntero.correr,
                                           TrabajoEntero.del_remoto)

    def subir_main(self, archivos, mensaje="cambio", vacio=False):
        trabajo = pathlib.Path(self.tmp.name) / "trabajo"
        if not trabajo.exists():
            g("clone", "-q", self.remoto, str(trabajo), cwd=self.tmp.name)
            g("config", "core.autocrlf", "false", cwd=trabajo)
        else:
            g("pull", "-q", "origin", "main", cwd=trabajo)
        for ruta, datos in archivos.items():
            (trabajo / ruta).parent.mkdir(parents=True, exist_ok=True)
            (trabajo / ruta).write_bytes(datos)
        g("add", "-A", cwd=trabajo)
        g("commit", "-q", *(["--allow-empty"] if vacio else []), "-m", mensaje, cwd=trabajo)
        g("push", "-q", "origin", "HEAD:main", cwd=trabajo)
        return g("rev-parse", "HEAD", cwd=trabajo)

    def preparar(self):
        catalogo = todo_el_modelo()
        archivos = sueltos_de(catalogo)
        canales_main = publicar._json({"esquema": 1, "versionCatalogo": catalogo["versionCatalogo"],
                                       "canales": publicar.canales_para_main(archivos)})
        self.subir_main({**archivos, "catalogo/catalogo.json": particion.texto_json(catalogo),
                         publicar.RUTA_CANALES_MAIN: canales_main})
        self.correr()
        return archivos

    def meses(self):
        salida = subprocess.run(["git", "--git-dir", self.remoto, "ls-tree", "-r", "--name-only", "main", "--",
                                 "historial/central/"], capture_output=True, check=True).stdout.decode().split()
        return {r: json.loads(self.del_remoto("main", r)) for r in salida}

    def test_un_cambio_en_la_ficha_deja_su_fila_con_el_catalogo(self):
        archivos = self.preparar()
        self.assertEqual({}, self.meses())
        juego = json.loads(archivos["juegos/rance-x/juego.json"])
        juego["titulo"] = "Rance X (nuevo)"
        juego["sinopsis"] = "Otra"
        sha = self.subir_main({"juegos/rance-x/juego.json": particion.texto_json(juego)},
                              f"Ficha (#42)\n\n{solicitudes.linea_historial(sol(), 'eva', 7, 42)}")
        api, avisos, _ = self.correr()
        meses = self.meses()
        self.assertEqual(1, len(meses))
        ruta, datos = next(iter(meses.items()))
        self.assertRegex(ruta, r"^historial/central/\d{4}-\d{2}\.json$")
        self.assertEqual((1, ruta[-12:-5]), (datos["esquema"], datos["mes"]))
        fila = datos["filas"][0]
        self.assertEqual({"canal": "rance_es", "cuenta": "eva", "cuentaId": 7, "tipo": "central", "juego": "rance-x",
                          "directa": True, "propuesta": 42, "commit": sha},
                         {k: v for k, v in fila.items() if k not in ("fecha", "cambios")})
        self.assertEqual({"juego.json": ["sinopsis", "titulo"]}, fila["cambios"])
        self.assertRegex(fila["fecha"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        # En la misma propuesta que el catálogo (una sola fusión), y el catálogo sube de versión.
        self.assertEqual(1, len([c for c in api.llamadas if c[0] == "PUT"]))
        self.assertEqual(32, json.loads(self.del_remoto("main", "catalogo/catalogo.json"))["versionCatalogo"])
        # Otra pasada: nada nuevo (la fila ya está en `main` y no se recalcula).
        api, avisos, _ = self.correr()
        self.assertFalse([c for c in api.llamadas if c[0] in ("PUT", "POST")])

    def test_solo_historial_no_sube_la_version_del_catalogo(self):
        self.preparar()
        self.subir_main({}, f"Algo (#7)\n\n{solicitudes.linea_historial(sol(tipo='edicion', directa=False), 'eva', 7, 7)}",
                        vacio=True)
        api, avisos, _ = self.correr()
        self.assertEqual(31, json.loads(self.del_remoto("main", "catalogo/catalogo.json"))["versionCatalogo"])
        propuesta = next(c for c in api.llamadas if c[:2] == ("POST", "/pulls"))[2]
        self.assertEqual("Historial global del programa", propuesta["title"])
        fila = next(iter(self.meses().values()))["filas"][0]
        self.assertEqual(({}, False, "edicion"), (fila["cambios"], fila["directa"], fila["tipo"]))

    def test_una_linea_rota_no_frena_nada_y_se_avisa(self):
        self.preparar()
        self.subir_main({}, solicitudes.MARCA_HISTORIAL + '{"v": 1, "canal": "../x"}', vacio=True)
        api, avisos, _ = self.correr()
        self.assertEqual({}, self.meses())
        self.assertTrue(any("no se entiende" in a for a in avisos))
        self.assertFalse([c for c in api.llamadas if c[0] == "PUT"])

    def test_edicion_nueva_e_imagen(self):
        archivos = self.preparar()
        juego = json.loads(archivos["juegos/rance-x/juego.json"])
        nuevos = {"juegos/rance-x/imagenes/portada-2.png": b"\x89PNG",
                  "juegos/rance-x/ediciones/zz-nueva.json": particion.texto_json({"esquema": 1, "id": "zz-nueva"})}
        self.subir_main({**nuevos, "juegos/rance-x/juego.json": particion.texto_json(juego)},
                        solicitudes.linea_historial(sol(tipo="edicion"), "eva", 7, 9))
        self.correr()
        fila = next(iter(self.meses().values()))["filas"][0]
        self.assertEqual({"ediciones/zz-nueva.json": "nuevo", "imagenes/portada-2.png": "cambiado"}, fila["cambios"])

    def test_un_mes_que_no_cabe_se_queda_con_lo_nuevo(self):
        self.preparar()
        for n in range(1, 6):
            self.subir_main({}, solicitudes.linea_historial(sol(), "eva", 7, n), vacio=True)
        with mock.patch.object(publicar, "TOPE_HISTORIAL", 900):
            api, avisos, _ = self.correr()
        datos = next(iter(self.meses().values()))
        self.assertLessEqual(len(publicar._json(datos)), 900)
        self.assertGreater(datos["recortadas"], 0)
        self.assertEqual(5, datos["recortadas"] + len(datos["filas"]))
        self.assertEqual(5, datos["filas"][-1]["propuesta"])  # se quedan las más nuevas
        self.assertTrue(any("recortadas" in a for a in avisos))

    def test_un_historial_ilegible_en_main_se_rehace(self):
        self.preparar()
        sha = self.subir_main({}, solicitudes.linea_historial(sol(), "eva", 7, 3), vacio=True)
        self.correr()
        ruta = next(iter(self.meses()))
        self.subir_main({ruta: b"{roto"})
        self.correr()
        self.assertEqual([sha], [f["commit"] for f in self.meses()[ruta]["filas"]])


if __name__ == "__main__":
    unittest.main()
