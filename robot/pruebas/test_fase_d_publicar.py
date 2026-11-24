"""Fase D, entrega 4: lo que `publicar` suma a la rama `publicado` para Modo equipo y el directorio de canales:
`miembros/<xx>.json`, `buscar-canales.json` y `paquetes` en `canales/<xx>.json`."""

import hashlib
import json
import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import listas  # noqa: E402
import particion  # noqa: E402
from test_particion import todo_el_modelo  # noqa: E402
from test_publicado_app import canal_de, canal_json, con_canales, publicados  # noqa: E402
from test_publicar import sueltos_de  # noqa: E402


def miembro(cuenta_id, cuenta, rol="editor", estado="activo", **otros):
    return {"id": cuenta_id, "cuenta": cuenta, "rol": rol, "estado": estado, **otros}


def con_miembros(archivos, cid, *filas):
    archivos = dict(archivos)
    archivos[f"canales/{cid}/miembros.json"] = particion.texto_json({"esquema": 1, "miembros": list(filas)})
    return archivos


def cuenta_de(salida, cuenta_id):
    ruta = f"miembros/{hashlib.sha256(str(cuenta_id).encode()).hexdigest()[:2]}.json"
    if ruta not in salida:
        return None
    return next((c for c in json.loads(salida[ruta])["cuentas"] if c["id"] == cuenta_id), None)


def base():
    archivos = con_canales(sueltos_de(), "rance_es", "viejo")
    archivos = con_miembros(archivos, "ornizen", miembro(1, "duena", "propietario"), miembro(7, "eva"))
    archivos = con_miembros(archivos, "rance_es", miembro(7, "eva", "propietario"),
                            miembro(8, "nuevo", "colaborador", "invitado", invitadoPor=7))
    return archivos


class Miembros(unittest.TestCase):
    def test_los_canales_de_cada_cuenta(self):
        salida = publicados(base(), todo_el_modelo())
        self.assertEqual({"id": 7, "cuenta": "eva", "canales": [
            {"canal": "ornizen", "rol": "editor", "estado": "activo"},
            {"canal": "rance_es", "rol": "propietario", "estado": "activo"}]}, cuenta_de(salida, 7))
        self.assertEqual([{"canal": "rance_es", "rol": "colaborador", "estado": "invitado", "invitadoPor": 7}],
                         cuenta_de(salida, 8)["canales"])
        # Van en el índice con su hash, como los demás trozos.
        trozos = json.loads(salida["indice.json"])["trozos"]
        for ruta in (r for r in salida if r.startswith("miembros/")):
            self.assertEqual("sha256:" + hashlib.sha256(salida[ruta]).hexdigest(), trozos[ruta])

    def test_ni_bloqueados_ni_vetados(self):
        archivos = base()
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", estado="bloqueado")
        archivos["canales/viejo/canal.json"] = canal_json("viejo", estado="retirado")
        archivos = con_miembros(archivos, "viejo", miembro(9, "vieja", "propietario"), miembro(10, "vetada"),
                                miembro(11, "vetada-canal"))
        archivos[listas.ruta_usuario(10)] = particion.texto_json({"esquema": 1, "usuarios": [
            {"id": 10, "cuenta": "vetada", "motivo": "Spam", "fecha": "2026-11-01"}]})
        archivos["canales/viejo/lista-negra.json"] = particion.texto_json({"esquema": 1, "archivos": [], "huellas": [],
            "usuarios": [{"id": 11, "cuenta": "vetada-canal", "motivo": "Abusos", "fecha": "2026-11-01", "por": 9}]})
        salida = publicados(archivos, todo_el_modelo())
        self.assertEqual(["ornizen"], [c["canal"] for c in cuenta_de(salida, 7)["canales"]])
        self.assertIsNone(cuenta_de(salida, 8))
        self.assertEqual(["viejo"], [c["canal"] for c in cuenta_de(salida, 9)["canales"]])  # retirado sí sale
        self.assertIsNone(cuenta_de(salida, 10))
        self.assertIsNone(cuenta_de(salida, 11))

    def test_un_veto_que_ya_paso_no_cuenta(self):
        archivos = base()
        archivos[listas.ruta_usuario(7)] = particion.texto_json({"esquema": 1, "usuarios": [
            {"id": 7, "cuenta": "eva", "motivo": "Spam", "fecha": "2026-01-01", "hasta": "2026-02-01"}]})
        self.assertIsNotNone(cuenta_de(publicados(archivos, todo_el_modelo()), 7))

    def test_un_trozo_general_ilegible_deja_fuera_a_sus_cuentas(self):
        archivos = base()
        archivos[listas.ruta_usuario(7)] = b"{roto"
        salida = publicados(archivos, todo_el_modelo())
        self.assertIsNone(cuenta_de(salida, 7))
        self.assertIsNotNone(cuenta_de(salida, 1))

    def test_un_canal_bloqueado_por_la_lista_general(self):
        archivos = base()
        archivos[listas.RUTA_CANALES] = particion.texto_json({"esquema": 1, "canales": [
            {"id": "rance_es", "esqueleto": "rancees", "motivo": "Malware", "fecha": "2026-11-20"}]})
        salida = publicados(archivos, todo_el_modelo())
        self.assertEqual("bloqueado", canal_de(salida, "rance_es")["estado"])
        self.assertEqual(["ornizen"], [c["canal"] for c in cuenta_de(salida, 7)["canales"]])

    def test_lo_ilegible_no_tumba_nada(self):
        archivos = base()
        archivos["canales/rance_es/miembros.json"] = b"{roto"
        archivos["canales/viejo/miembros.json"] = particion.texto_json({"esquema": 1, "miembros": "no"})
        salida = publicados(archivos, todo_el_modelo())
        self.assertEqual(["ornizen"], [c["canal"] for c in cuenta_de(salida, 7)["canales"]])
        self.assertIsNone(cuenta_de(salida, 8))

    def test_el_dueno_no_sale_por_serlo(self):
        archivos = con_canales(sueltos_de(), "rance_es")
        archivos["normas/propietario.json"] = particion.texto_json({"ids": [1]})
        self.assertFalse([r for r in publicados(archivos, todo_el_modelo()) if r.startswith("miembros/")])


class Directorio(unittest.TestCase):
    def test_todos_menos_los_ocultos(self):
        archivos = base()
        archivos["canales/viejo/canal.json"] = canal_json("viejo", oculto=True)
        directorio = json.loads(publicados(archivos, todo_el_modelo())["buscar-canales.json"])
        self.assertEqual(1, directorio["esquema"])
        self.assertEqual(["ornizen", "rance_es"], [c["id"] for c in directorio["canales"]])
        ornizen = directorio["canales"][0]
        self.assertEqual({"id", "nombre", "verificado", "estado", "adultos", "parches"}, set(ornizen))
        self.assertTrue(ornizen["verificado"])
        self.assertGreaterEqual(ornizen["parches"], 1)
        self.assertEqual(0, directorio["canales"][1]["parches"])

    def test_sin_canales_no_hay_directorio(self):
        self.assertNotIn("buscar-canales.json", publicados(sueltos_de(), todo_el_modelo()))

    def test_paquetes_en_el_trozo_del_canal(self):
        archivos = base()
        archivos["canales/rance_es/canal.json"] = canal_json(
            "rance_es", paquetes=["rance-es/parches", "mal formado", "rance-es/otro", "a/b", "c/d"])
        self.assertEqual(["a/b", "c/d", "rance-es/otro"],
                         canal_de(publicados(archivos, todo_el_modelo()), "rance_es")["paquetes"])


class Extremos(unittest.TestCase):
    def test_cinco_mil_canales_y_cuentas(self):
        archivos = sueltos_de()
        archivos["canales/ornizen/canal.json"] = canal_json("ornizen")
        for i in range(5000):
            cid = f"c{i:04d}"
            archivos[f"canales/{cid}/canal.json"] = canal_json(cid)
            archivos[f"canales/{cid}/miembros.json"] = particion.texto_json({"esquema": 1, "miembros": [
                miembro(100000 + i, f"p{i}", "propietario"), miembro(7, "eva")]})
        inicio = time.monotonic()
        salida = publicados(archivos, todo_el_modelo())
        self.assertLess(time.monotonic() - inicio, 60)
        self.assertEqual(5000, len(cuenta_de(salida, 7)["canales"]))
        self.assertEqual(5001, len(json.loads(salida["buscar-canales.json"])["canales"]))
        self.assertLess(len(salida["buscar-canales.json"]), 1024 * 1024)
        self.assertLessEqual(len([r for r in salida if r.startswith("miembros/")]), 256)


class ConGit(unittest.TestCase):
    """El trabajo entero lee de `main` los `miembros.json`, las listas negras y la lista negra general."""

    def test_miembros_desde_main(self):
        import test_publicar
        trabajo = test_publicar.TrabajoEntero("test_antes_de_la_migracion_solo_el_indice")
        trabajo.setUp()
        try:
            catalogo = todo_el_modelo()
            archivos = base()
            archivos[listas.ruta_usuario(8)] = particion.texto_json({"esquema": 1, "usuarios": [
                {"id": 8, "cuenta": "nuevo", "motivo": "Spam", "fecha": "2026-11-01"}]})
            trabajo.subir_main({**archivos, "catalogo/catalogo.json": particion.texto_json(catalogo)})
            trabajo.correr()
            salida = {}
            for ident in (7, 8):
                ruta = f"miembros/{hashlib.sha256(str(ident).encode()).hexdigest()[:2]}.json"
                try:
                    salida[ruta] = trabajo.del_remoto("publicado", ruta)
                except Exception:  # noqa: BLE001 — sin el trozo, la cuenta no sale
                    pass
            self.assertEqual(["ornizen", "rance_es"], [c["canal"] for c in cuenta_de(salida, 7)["canales"]])
            self.assertIsNone(cuenta_de(salida, 8))
            self.assertIn(b"rance_es", trabajo.del_remoto("publicado", "buscar-canales.json"))
        finally:
            trabajo.tearDown()


if __name__ == "__main__":
    unittest.main()
