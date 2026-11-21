"""Pruebas de la lista de archivos ignorados de una edición.  Uso:  python -m unittest discover -s robot/pruebas"""
import copy
import hashlib
import io
import json
import pathlib
import sys
import unittest
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from permisos import (Cambio, Permisos, Rol, RUTA_CATALOGO, comprobar, error_de_patron, regex_ignorar,  # noqa: E402
                      rutas_del_paquete, validar_ignorados)

HASH = "blake3:" + "a" * 64
EDITOR, COLABORADOR, PROPIETARIO = Permisos(Rol.EDITOR), Permisos(Rol.COLABORADOR), Permisos(Rol.PROPIETARIO)


def archivo(ruta, tamano=1000):
    return {"ruta": ruta, "tamano": tamano, "hashParcial": HASH, "hash": HASH}


def edicion(**cambios):
    """Una edición de 10 archivos de 1000 bytes, con el parche 1.0.0 que cambia `texto.ain`."""
    base = {
        "id": "steam", "nombre": "Steam",
        "huella": [archivo("Juego.exe"), archivo("texto.ain")] + [archivo(f"datos/d{i}.afa") for i in range(8)],
        "huellasParcheadas": [{"version": "1.0.0", "archivos": [archivo("texto.ain"), archivo("fuentes/nueva.ttf")]}],
    }
    base.update(cambios)
    return base


def errores(**cambios):
    return validar_ignorados("`juego1` › edición `steam`", edicion(**cambios))


BASE = {"esquema": 1, "versionCatalogo": 5, "etiquetas": [],
        "juegos": [{"id": "juego1", "titulo": "Juego 1", "ediciones": [edicion()]}]}


def revisar(permisos, cambiar, leer_paquete=None):
    despues = copy.deepcopy(BASE)
    despues["versionCatalogo"] += 1
    cambiar(despues["juegos"][0]["ediciones"][0], despues["juegos"][0])
    return comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(BASE), json.dumps(despues), permisos, leer_paquete=leer_paquete)


class Patrones(unittest.TestCase):
    def test_prohibidos(self):
        for patron in ("*", "**", "**/*", "*.*", "**/*.*", "*/*", "", "   ", "../partidas", "datos/../../x",
                       "/config.ini", "C:\\Juego\\config.ini", "*.exe", "*.DLL", "Juego.exe", "bin/**/*.dll",
                       "a" * 201, "con\nsalto.ini", None, 7, ["x"]):
            self.assertIsNotNone(error_de_patron(patron), repr(patron))

    def test_que_valen(self):
        for patron in ("config.ini", "UserData/**", "*.cfg", "cache\\shaders\\*.bin", "datos/d0?.afa"):
            self.assertIsNone(error_de_patron(patron), patron)

    def test_encajan_como_en_el_parcheador(self):
        casos = [("config.ini", "config.ini", True), ("config.ini", "sub/CONFIG.INI", True), ("config.ini", "config.ini.bak", False),
                 ("UserData/**", "userdata/a/b.cfg", True), ("UserData/**", "datos/UserData/a", False),
                 ("*.cfg", "a/b/c.cfg", True), ("datos/*.afa", "datos/x.afa", True), ("datos/*.afa", "datos/sub/x.afa", False),
                 ("datos/**/x.afa", "datos/x.afa", True), ("datos/**/x.afa", "datos/a/b/x.afa", True),
                 ("d?.dat", "d1.dat", True), ("d?.dat", "d12.dat", False), ("a+b(1).ini", "a+b(1).ini", True)]
        for patron, ruta, esperado in casos:
            self.assertEqual(esperado, bool(regex_ignorar(patron).match(ruta)), (patron, ruta))


class Edicion(unittest.TestCase):
    def test_sin_lista_no_hay_nada_que_mirar(self):
        self.assertEqual([], errores())
        self.assertEqual([], errores(ignorar=[]))

    def test_una_lista_que_vale(self):
        self.assertEqual([], errores(ignorar=["config.ini", "UserData/**"], ignorados={"archivos": 3, "bytes": 90}))

    def test_justo_en_el_limite_y_uno_mas(self):
        # 10 archivos en la huella: con 4 ignorados quedan 10 de 14 (71 %); con 5, 10 de 15 (67 %).
        self.assertEqual([], errores(ignorar=["config.ini"], ignorados={"archivos": 4, "bytes": 0}))
        self.assertIn("70%", errores(ignorar=["config.ini"], ignorados={"archivos": 5, "bytes": 0})[0])
        # 10.000 bytes en la huella: con 2.500 ignorados queda el 80 %; con 2.501, no.
        self.assertEqual([], errores(ignorar=["config.ini"], ignorados={"archivos": 0, "bytes": 2500}))
        self.assertIn("80%", errores(ignorar=["config.ini"], ignorados={"archivos": 0, "bytes": 2501})[0])

    def test_todo_ignorado_menos_el_exe(self):
        solo_exe = [archivo("Juego.exe")]
        motivos = errores(huella=solo_exe, huellasParcheadas=[], ignorar=["datos/**", "texto.ain"], ignorados={"archivos": 9, "bytes": 9000})
        self.assertEqual(2, len(motivos))
        for patron in ("**", "*", "*.*", "**/*"):
            self.assertIn("cualquier archivo", errores(huella=solo_exe, ignorar=[patron], ignorados={"archivos": 0, "bytes": 0})[0])

    def test_no_se_ignora_lo_que_toca_el_parche(self):
        motivos = errores(huella=[archivo("Juego.exe")] + [archivo(f"datos/d{i}.afa") for i in range(8)],
                          ignorar=["texto.ain", "fuentes/**"], ignorados={"archivos": 1, "bytes": 1000})
        self.assertEqual(2, len(motivos))
        self.assertTrue(all("el parche" in m for m in motivos))

    def test_lo_ignorado_no_puede_seguir_en_la_huella(self):
        self.assertIn("no entra en la huella", errores(ignorar=["datos/d3.afa"], ignorados={"archivos": 1, "bytes": 1000})[0])

    def test_ejecutables(self):
        self.assertIn("ejecutables", errores(ignorar=["plugins/*.dll"], ignorados={"archivos": 1, "bytes": 1})[0])

    def test_demasiados_patrones(self):
        self.assertIn("máximo", errores(ignorar=[f"nada{i}.ini" for i in range(51)], ignorados={"archivos": 0, "bytes": 0})[0])
        self.assertEqual([], errores(ignorar=[f"nada{i}.ini" for i in range(50)], ignorados={"archivos": 0, "bytes": 0}))

    def test_resumen_que_falta_o_esta_mal(self):
        for resumen in (None, {}, {"archivos": 1}, {"archivos": -1, "bytes": 0}, {"archivos": "3", "bytes": 0},
                        {"archivos": True, "bytes": 0}, [1, 2], "3"):
            self.assertIn("`ignorados`", errores(ignorar=["config.ini"], ignorados=resumen)[0], repr(resumen))

    def test_formas_raras_no_rompen_el_robot(self):
        self.assertIn("lista de patrones", errores(ignorar="config.ini")[0])
        self.assertIn("lista de patrones", errores(ignorados={"archivos": 1, "bytes": 1})[0])
        self.assertIn("sobra", errores(ignorar=[], ignorados={"archivos": 1, "bytes": 1})[0])
        self.assertEqual([], errores(huella=None, huellasParcheadas=[None, {"archivos": [None, {"ruta": 5}]}],
                                     ignorar=["config.ini"], ignorados={"archivos": 0, "bytes": 0}))
        self.assertEqual([], errores(huella=[], huellasParcheadas=None, ignorar=["config.ini"], ignorados={"archivos": 0, "bytes": 0}))


class EnUnaPropuesta(unittest.TestCase):
    def test_un_editor_puede_poner_una_lista_que_vale(self):
        self.assertEqual([], revisar(EDITOR, lambda e, j: e.update(ignorar=["config.ini"], ignorados={"archivos": 1, "bytes": 50})))

    def test_un_colaborador_no(self):
        motivos = revisar(COLABORADOR, lambda e, j: e.update(ignorar=["config.ini"], ignorados={"archivos": 1, "bytes": 50}))
        self.assertTrue(motivos)

    def test_ni_el_propietario_se_salta_las_reglas(self):
        motivos = revisar(PROPIETARIO, lambda e, j: e.update(ignorar=["**"], ignorados={"archivos": 0, "bytes": 0}))
        self.assertEqual(1, len(motivos))
        self.assertIn("cualquier archivo", motivos[0])

    def test_un_paquete_nuevo_no_puede_tocar_un_archivo_ignorado(self):
        memoria = io.BytesIO()
        with zipfile.ZipFile(memoria, "w") as z:
            z.writestr("manifiesto.json", json.dumps({
                "esquema": 1, "juego": "juego1", "edicion": "steam", "version": "1.1.0",
                "operaciones": [{"ruta": "config.ini", "tipo": "nuevo", "archivo": "nuevos/0"}]}))
            z.writestr("nuevos/0", b"x")
        datos = memoria.getvalue()

        class Sha256:
            def __init__(self):
                self._h = hashlib.sha256()

            def update(self, trozo):
                self._h.update(trozo)

            def hexdigest(self):
                return self._h.hexdigest()

        def cambiar(e, j):
            e.update(ignorar=["config.ini"], ignorados={"archivos": 1, "bytes": 50})
            j["parche"] = {"version": "1.1.0", "paquetes": [{
                "edicion": "steam", "url": "https://example.org/n.zip", "tamano": len(datos),
                "hash": "blake3:" + hashlib.sha256(datos).hexdigest()}]}

        motivos = revisar(PROPIETARIO, cambiar, leer_paquete=lambda p: rutas_del_paquete(
            p, calcular_hash=Sha256, abrir=lambda url: io.BytesIO(datos)))
        self.assertEqual(1, len(motivos))
        self.assertIn("que la edición ignora con `config.ini`", motivos[0])


if __name__ == "__main__":
    unittest.main()
