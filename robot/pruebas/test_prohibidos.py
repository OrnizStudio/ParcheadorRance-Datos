"""Pruebas de la lista de archivos prohibidos.  Uso:  python -m unittest discover -s robot/pruebas"""
import copy
import hashlib
import io
import json
import pathlib
import sys
import unittest
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "robot"))
from permisos import (Cambio, PaqueteIlegible, Permisos, Prohibido, Rol, RUTA_CATALOGO, RUTA_PROHIBIDOS,  # noqa: E402
                      RUTA_PROPIETARIO, archivo_prohibido, comprobar, leer_prohibidos, leer_propietarios,
                      permisos_de, rutas_del_paquete)

LISTA = leer_prohibidos((RAIZ / RUTA_PROHIBIDOS).read_text(encoding="utf-8"))
ADMIN = Permisos(Rol.ADMINISTRADOR)
MENSAJE = "Los parches no pueden modificar archivos de protección anticopia."


class Sha256EnLugarDeBlake3:
    """Sustituye a BLAKE3 en las pruebas (así no hace falta instalarlo)."""
    def __init__(self):
        self._h = hashlib.sha256()

    def update(self, datos):
        self._h.update(datos)

    def hexdigest(self):
        return self._h.hexdigest()


def zip_con(rutas, manifiesto=True):
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as z:
        if manifiesto:
            z.writestr("manifiesto.json", json.dumps({
                "esquema": 1, "juego": "juego1", "edicion": "steam", "version": "1.1.0",
                "operaciones": [{"ruta": r, "tipo": "nuevo", "archivo": f"nuevos/{i}"} for i, r in enumerate(rutas)]}))
        for i, _ in enumerate(rutas):
            z.writestr(f"nuevos/{i}", b"x")
    return memoria.getvalue()


def paquete_de(datos, url="https://example.org/nuevo.zip"):
    return {"edicion": "steam", "url": url, "tamano": len(datos), "hash": "blake3:" + hashlib.sha256(datos).hexdigest()}


def lector(servidos):
    """leer_paquete que «descarga» de un diccionario url -> bytes."""
    def leer(paquete):
        return rutas_del_paquete(paquete, calcular_hash=Sha256EnLugarDeBlake3,
                                 abrir=lambda url: io.BytesIO(servidos[url]))
    return leer


BASE = {
    "esquema": 1, "versionCatalogo": 5, "etiquetas": [],
    "juegos": [{"id": "juego1", "ediciones": [{"id": "steam", "huella": [
        {"ruta": "steam_api64.dll", "tamano": 1, "hashParcial": "blake3:" + "a" * 64, "hash": "blake3:" + "a" * 64}]}],
        "parche": {"version": "1.0.0", "paquetes": [paquete_de(zip_con(["Datos/textos.dat"]), "https://example.org/viejo.zip")]}}],
}


def revisar(cambiar, servidos=None, permisos=ADMIN):
    despues = copy.deepcopy(BASE)
    despues["versionCatalogo"] += 1
    cambiar(despues)
    return comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(BASE), json.dumps(despues), permisos,
                     prohibidos=LISTA, leer_paquete=lector(servidos or {}))


class Patrones(unittest.TestCase):
    def test_lo_minimo_esta_en_la_lista(self):
        for ruta in ["steam_api.dll", "steam_api64.dll", "steamclient.dll", "steamclient64.dll", "x/datos.cdx",
                     "uplay_r1_loader64.dll", "EOSSDK-Win64-Shipping.dll", "EOSSDK-Win32-Shipping.dll",
                     "galaxy.dll", "galaxy64.dll", "denuvo64.dll", "steam_emu.ini", "steam_settings/force_language.txt",
                     "CODEX.ini", "codex64.dll", "SmartSteamEmu.ini", "SmartSteamEmu/plugins/x.dll", "cream_api.ini"]:
            with self.subTest(ruta=ruta):
                self.assertIsNotNone(archivo_prohibido(ruta, LISTA))

    def test_sin_distinguir_mayusculas_y_en_cualquier_carpeta(self):
        for ruta in ["STEAM_API64.DLL", "Bin/Win64/Steam_Api64.dll", "bin\\steam_api64.dll", "a/STEAM_SETTINGS/b.txt"]:
            with self.subTest(ruta=ruta):
                self.assertIsNotNone(archivo_prohibido(ruta, LISTA))

    def test_archivos_normales_no(self):
        for ruta in ["Datos/textos.dat", "Fuentes/fuente.ttf", "steam_api64.dll.txt", "LEEME.txt", "Rance.exe",
                     "config.ini", "steam_settings.txt", "galaxy_textos.dat", "Datos/steam_settings"]:
            with self.subTest(ruta=ruta):
                self.assertIsNone(archivo_prohibido(ruta, LISTA))

    def test_patron_con_ruta(self):
        self.assertTrue(Prohibido("bin/*.sig").coincide("BIN/a.sig"))
        self.assertFalse(Prohibido("bin/*.sig").coincide("otra/bin/a.sig"))

    def test_lista_mal_escrita(self):
        for texto in ['{}', '{"patrones": []}', '{"patrones": [{"patron": "  "}]}', '{"patrones": ["x"]}']:
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                leer_prohibidos(texto)


class Catalogo(unittest.TestCase):
    def test_huella_parcheada_con_un_archivo_protegido_se_rechaza_tambien_al_administrador(self):
        def cambiar(c):
            c["juegos"][0]["ediciones"][0]["huellasParcheadas"] = [
                {"version": "1.1.0", "archivos": [{"ruta": "Steam_Api64.dll", "tamano": 1, "hashParcial": "blake3:" + "b" * 64, "hash": "blake3:" + "b" * 64}]}]
        motivos = revisar(cambiar)
        self.assertEqual(1, len(motivos))
        self.assertIn("Este parche toca un archivo protegido (Steam_Api64.dll). " + MENSAJE, motivos[0])

    def test_la_huella_del_juego_original_no_cuenta(self):
        # La huella de la edición describe el juego tal cual se compra: lleva steam_api64.dll y es normal.
        self.assertEqual([], revisar(lambda c: c["juegos"][0].update(titulo="Otro")))

    def test_paquete_nuevo_que_escribe_un_archivo_protegido(self):
        datos = zip_con(["Datos/textos.dat", "steam_api64.dll"])

        def cambiar(c):
            c["juegos"][0]["parche"]["paquetes"] = [paquete_de(datos)]
        motivos = revisar(cambiar, {"https://example.org/nuevo.zip": datos})
        self.assertEqual(1, len(motivos))
        self.assertIn("(steam_api64.dll). " + MENSAJE, motivos[0])
        self.assertIn("`juego1` › paquete `steam`", motivos[0])

    def test_paquete_en_el_historial_de_versiones(self):
        datos = zip_con(["steam_settings/configs.user.ini"])

        def cambiar(c):
            c["juegos"][0]["ediciones"][0]["versiones"] = [{"version": "2.0.0", "paquetes": [paquete_de(datos)]}]
        motivos = revisar(cambiar, {"https://example.org/nuevo.zip": datos})
        self.assertEqual(1, len(motivos))
        self.assertIn("steam_settings/configs.user.ini", motivos[0])

    def test_paquete_nuevo_limpio(self):
        datos = zip_con(["Datos/textos.dat", "Fuentes/fuente.ttf"])

        def cambiar(c):
            c["juegos"][0]["parche"]["paquetes"] = [paquete_de(datos)]
        self.assertEqual([], revisar(cambiar, {"https://example.org/nuevo.zip": datos}))

    def test_los_paquetes_ya_publicados_no_se_vuelven_a_descargar(self):
        # El lector no sirve nada: si intentara descargar el paquete viejo, fallaría.
        self.assertEqual([], revisar(lambda c: c["juegos"][0].update(titulo="Otro")))

    def test_paquete_que_no_coincide_con_el_catalogo(self):
        datos = zip_con(["Datos/textos.dat"])

        def cambiar(c):
            c["juegos"][0]["parche"]["paquetes"] = [paquete_de(datos)]
        # Se sirve otro archivo (por ejemplo, porque lo han cambiado en la Release): se rechaza.
        motivos = revisar(cambiar, {"https://example.org/nuevo.zip": zip_con(["steam_api.dll"])})
        self.assertEqual(1, len(motivos))
        self.assertIn("no se ha podido revisar el paquete", motivos[0])


def con_lista_de_grupo(patrones, nombre="Ornizen"):
    def poner(c):
        c["grupo"] = {"nombre": nombre, "archivosProhibidos": patrones}
    return poner


def huella_que_toca(*rutas):
    def poner(c):
        c["juegos"][0]["ediciones"][0]["huellasParcheadas"] = [
            {"version": "1.1.0", "archivos": [{"ruta": r, "tamano": 1, "hashParcial": "blake3:" + "b" * 64, "hash": "blake3:" + "b" * 64} for r in rutas]}]
    return poner


def varios(*cambios):
    def cambiar(c):
        for cambio in cambios:
            cambio(c)
    return cambiar


class ListaDelGrupo(unittest.TestCase):
    def test_el_grupo_anade_sus_propios_archivos(self):
        motivos = revisar(varios(con_lista_de_grupo([{"patron": "*.sig", "motivo": "Firma del juego."}]),
                                 huella_que_toca("Datos/juego.sig")))
        self.assertEqual(1, len(motivos))
        self.assertIn("(Datos/juego.sig). " + MENSAJE, motivos[0])
        self.assertIn("lista **del grupo Ornizen**", motivos[0])
        self.assertIn("`grupo.archivosProhibidos`", motivos[0])

    def test_tambien_en_los_paquetes(self):
        datos = zip_con(["Datos/juego.sig"])

        def cambiar(c):
            con_lista_de_grupo([{"patron": "*.sig"}])(c)
            c["juegos"][0]["parche"]["paquetes"] = [paquete_de(datos)]
        motivos = revisar(cambiar, {"https://example.org/nuevo.zip": datos})
        self.assertEqual(1, len(motivos))
        self.assertIn("del grupo Ornizen", motivos[0])

    def test_el_aviso_de_la_general_dice_general(self):
        motivos = revisar(varios(con_lista_de_grupo([{"patron": "steam_api64.dll"}]), huella_que_toca("steam_api64.dll")))
        self.assertEqual(1, len(motivos))
        self.assertIn("lista **general**", motivos[0])
        self.assertIn("`normas/archivos-prohibidos.json`", motivos[0])

    def test_no_puede_saltarse_la_general(self):
        # No hay sintaxis de excepción: un «!» es un patrón más (que no coincide con nada), no un permiso.
        motivos = revisar(varios(con_lista_de_grupo([{"patron": "!steam_api64.dll"}]), huella_que_toca("steam_api64.dll")))
        self.assertEqual(1, len(motivos))
        self.assertIn("lista **general**", motivos[0])

    def test_quitar_una_entrada_no_vale_en_la_misma_propuesta(self):
        antes = copy.deepcopy(BASE)
        con_lista_de_grupo([{"patron": "*.sig"}])(antes)
        despues = copy.deepcopy(antes)
        despues["versionCatalogo"] += 1
        despues["grupo"]["archivosProhibidos"] = []
        huella_que_toca("a.sig")(despues)
        motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(antes), json.dumps(despues), ADMIN,
                            prohibidos=LISTA, leer_paquete=lector({}))
        self.assertEqual(1, len(motivos))
        self.assertIn("del grupo Ornizen", motivos[0])

    def test_sin_nombre_de_grupo(self):
        motivos = revisar(varios(con_lista_de_grupo([{"patron": "*.sig"}], nombre=""), huella_que_toca("a.sig")))
        self.assertIn("lista **del grupo**:", motivos[0])

    def test_lista_mal_escrita(self):
        self.assertIn("tiene que ser una lista", revisar(con_lista_de_grupo("*.sig"))[0])
        self.assertIn("patrón vacío", revisar(con_lista_de_grupo([{"patron": ""}]))[0])

    def test_un_editor_no_la_cambia(self):
        motivos = revisar(con_lista_de_grupo([{"patron": "*.sig"}]), permisos=Permisos(Rol.EDITOR))
        self.assertEqual(1, len(motivos))
        self.assertIn("`grupo`: esta parte del catálogo solo la cambia un Administrador", motivos[0])


class ListaGeneralYPropietario(unittest.TestCase):
    def proponer_cambio_de_normas(self, permisos):
        return comprobar([Cambio(RUTA_PROHIBIDOS, "M")], json.dumps(BASE), json.dumps(BASE), permisos)

    def test_solo_el_propietario_cambia_la_lista_general(self):
        self.assertEqual([], self.proponer_cambio_de_normas(Permisos(Rol.PROPIETARIO)))
        for rol in (Rol.ADMINISTRADOR, Rol.EDITOR, Rol.COLABORADOR):
            with self.subTest(rol=rol):
                motivos = self.proponer_cambio_de_normas(Permisos(rol))
                self.assertEqual(1, len(motivos))
                self.assertIn("solo lo cambia el Propietario", motivos[0])

    def test_el_propietario_tambien_queda_sujeto_a_la_lista(self):
        motivos = revisar(huella_que_toca("steam_api.dll"), permisos=Permisos(Rol.PROPIETARIO))
        self.assertEqual(1, len(motivos))
        self.assertIn(MENSAJE, motivos[0])

    def test_quien_es_propietario(self):
        propietarios = leer_propietarios((RAIZ / RUTA_PROPIETARIO).read_text(encoding="utf-8"))

        def api(nivel):
            return lambda metodo, ruta, tolerar=(): {"role_name": nivel}
        cuenta = next(iter(propietarios))
        self.assertEqual(Rol.PROPIETARIO, permisos_de(cuenta.upper(), api("admin"), {}, propietarios).rol_global)
        self.assertEqual(Rol.ADMINISTRADOR, permisos_de("otra-cuenta", api("admin"), {}, propietarios).rol_global)
        # Figurar en la lista no basta: hace falta además ser admin del repositorio.
        self.assertEqual(Rol.EDITOR, permisos_de(cuenta, api("write"), {}, propietarios).rol_global)

    def test_archivo_de_propietario_mal_escrito(self):
        for texto in ['{}', '{"propietario": []}', '{"propietario": [""]}', '{"propietario": 3}']:
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                leer_propietarios(texto)
        self.assertEqual({"alguien"}, leer_propietarios('{"propietario": "Alguien"}'))


class LeerPaquete(unittest.TestCase):
    def leer(self, servido, paquete):
        return rutas_del_paquete(paquete, calcular_hash=Sha256EnLugarDeBlake3, abrir=lambda url: io.BytesIO(servido))

    def test_lee_las_rutas_del_manifiesto(self):
        datos = zip_con(["a.dat", "b/c.dat"])
        self.assertEqual(["a.dat", "b/c.dat"], self.leer(datos, paquete_de(datos)))

    def test_hash_distinto(self):
        datos = zip_con(["a.dat"])
        paquete = dict(paquete_de(datos), hash="blake3:" + "0" * 64)
        with self.assertRaisesRegex(PaqueteIlegible, "hash"):
            self.leer(datos, paquete)

    def test_mas_grande_de_lo_dicho(self):
        datos = zip_con(["a.dat"])
        with self.assertRaisesRegex(PaqueteIlegible, "pesa más"):
            self.leer(datos + b"x", paquete_de(datos))

    def test_sin_manifiesto_o_no_es_zip(self):
        for datos in [zip_con(["a.dat"], manifiesto=False), b"esto no es un zip"]:
            with self.subTest(), self.assertRaises(PaqueteIlegible):
                self.leer(datos, paquete_de(datos))

    def test_sin_https(self):
        with self.assertRaises(PaqueteIlegible):
            self.leer(b"", {"url": "http://x/p.zip", "tamano": 1, "hashParcial": "blake3:" + "a" * 64, "hash": "blake3:" + "a" * 64})

    def test_con_blake3_de_verdad_si_esta_instalado(self):
        try:
            import blake3
        except ImportError:
            self.skipTest("blake3 no está instalado")
        datos = zip_con(["steam_api64.dll"])
        paquete = {"url": "https://x/p.zip", "tamano": len(datos), "hash": "blake3:" + blake3.blake3(datos).hexdigest()}
        self.assertEqual(["steam_api64.dll"], rutas_del_paquete(paquete, abrir=lambda url: io.BytesIO(datos)))


if __name__ == "__main__":
    unittest.main()
