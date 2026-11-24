"""Fase B: propuestas sobre los archivos sueltos del catálogo (`robot/sueltos.py`, integrado en `permisos.comprobar`).

Cada caso es una propuesta entera: los archivos de `main` (el catálogo ya migrado) y los de después, juzgados con el
rol de quien propone. Las reglas de siempre (campos por rol, lo que la app puede leer) se aplican al catálogo que
resulta de juntar los archivos; las nuevas (alta, estado central, huella, versiones, coherencia, paquetes) son de
`sueltos.py`.
"""

import copy
import datetime
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import particion  # noqa: E402
import sueltos  # noqa: E402
from permisos import ACTUALIZA_EL_PARCHEADOR, Cambio, Permisos, Rol, RUTA_CATALOGO, comprobar  # noqa: E402

HOY = datetime.date(2026, 11, 24)
YO = 4242
HASH = "blake3:" + "b" * 64
HUELLA = [{"ruta": "Rance.exe", "tamano": 10, "hashParcial": HASH, "hash": HASH}]
REPO = "OrnizStudio/ParcheadorRance-Datos"
URL = f"https://github.com/{REPO}/releases/download/rance-1.0.0/rance.zip"
CATALOGO = {
    "esquema": 1, "versionCatalogo": 31,
    "launcher": {"ultimaVersion": "0.2.3"},
    "etiquetas": [{"id": "rpg", "nombre": "RPG"}],
    "juegos": [{
        "id": "rance", "habilitado": True, "orden": 1, "titulo": "Rance", "sinopsis": "Antes", "etiquetas": ["rpg"],
        "estado": "publico", "progreso": {"traduccion": 50},
        "ediciones": [{
            "id": "steam", "nombre": "Steam", "huella": HUELLA, "notaEdicion": "",
            "versiones": [{"version": "1.0.0", "estado": "publica", "fecha": "2026-11-01", "autor": "ana",
                           "notas": "primera", "paquete": {"url": URL, "tamano": 5, "hash": HASH}}],
        }],
        "parche": {"version": "1.0.0", "paquetes": [{"edicion": "steam", "url": URL, "tamano": 5, "hash": HASH}]},
    }],
}
CANAL = {"esquema": 1, "id": "ornizen", "nombre": "Ornizen", "paquetes": [REPO]}


def permisos(rol, cuenta_id=YO):
    if rol >= Rol.DUENO:
        return Permisos(Rol.DUENO, cuenta_id=cuenta_id)
    return Permisos(rol, por_canal={"ornizen": rol} if rol else {}, cuenta_id=cuenta_id)


def main_migrado():
    archivos = particion.partir(copy.deepcopy(CATALOGO))
    archivos["canales/ornizen/canal.json"] = particion.texto_json(CANAL)
    return archivos


class Propuesta:
    """Los archivos de `main` y los de la propuesta; `juzgar` da los motivos de rechazo."""

    def __init__(self, main=None):
        self.antes = main_migrado() if main is None else main
        self.despues = dict(self.antes)

    def leer(self, ruta, lado="despues"):
        return json.loads((self.antes if lado == "antes" else self.despues)[ruta])

    def poner(self, ruta, valor):
        self.despues[ruta] = valor if isinstance(valor, bytes) else particion.texto_json(valor)
        return self

    def cambiar(self, ruta, cambio):
        objeto = self.leer(ruta)
        cambio(objeto)
        return self.poner(ruta, objeto)

    def quitar(self, ruta):
        del self.despues[ruta]
        return self

    def cambios(self, extra=()):
        rutas = set(self.antes) | set(self.despues)
        resultado = []
        for ruta in sorted(rutas):
            if ruta not in self.despues:
                resultado.append(Cambio(ruta, "D"))
            elif ruta not in self.antes:
                resultado.append(Cambio(ruta, "A", tamano=len(self.despues[ruta])))
            elif self.antes[ruta] != self.despues[ruta]:
                resultado.append(Cambio(ruta, "M", tamano=len(self.despues[ruta])))
        return resultado + list(extra)

    def juzgar(self, rol, cuenta_id=YO, extra=(), catalogo_despues=None):
        texto_main = particion.texto_json(CATALOGO).decode("utf-8")
        return comprobar(self.cambios(extra), texto_main, catalogo_despues or texto_main.encode(),
                         permisos(rol, cuenta_id), leer_sueltos=lambda lado: self.antes if lado == "antes" else self.despues,
                         hoy=HOY)


JUEGO = "juegos/rance/juego.json"
EDICION = "juegos/rance/ediciones/steam.json"
PARCHE = "canales/ornizen/parches/rance.json"


def alta(cuenta=YO, fecha=HOY.isoformat(), canal="ornizen"):
    return {"canal": canal, "cuenta": cuenta, "fecha": fecha}


def juego_nuevo(p: Propuesta, jid="rance-2", con_alta=None, edicion_alta=None):
    p.poner(f"juegos/{jid}/juego.json", {"esquema": 1, "id": jid, "titulo": "Rance 2", "estado": "activo",
                                          "alta": con_alta or alta(), "ediciones": ["dl"]})
    p.poner(f"juegos/{jid}/ediciones/dl.json", {"esquema": 1, "id": "dl", "nombre": "DL", "huella": HUELLA,
                                                 "alta": edicion_alta or alta()})
    p.poner(f"canales/ornizen/parches/{jid}.json", {"esquema": 1, "juego": jid, "habilitado": False, "orden": 2,
                                                     "ediciones": [{"id": "dl"}]})
    return p


class LoDeSiempre(unittest.TestCase):
    """Las reglas por rol de `catalogo.json` siguen valiendo, ahora sobre los archivos sueltos."""

    def test_un_colaborador_cambia_la_sinopsis_y_no_el_titulo(self):
        self.assertEqual([], Propuesta().cambiar(JUEGO, lambda j: j.update(sinopsis="Después")).juzgar(Rol.COLABORADOR))
        motivos = Propuesta().cambiar(JUEGO, lambda j: j.update(titulo="Otro")).juzgar(Rol.COLABORADOR)
        self.assertTrue(any("`titulo`" in m for m in motivos), motivos)

    def test_un_editor_no_publica_el_juego_entero(self):
        motivos = Propuesta().cambiar(PARCHE, lambda p: p.update(habilitado=False)).juzgar(Rol.EDITOR)
        self.assertTrue(any("habilitado" in m for m in motivos), motivos)

    def test_sin_rol_no_toca_nada(self):
        motivos = Propuesta().cambiar(PARCHE, lambda p: p.update(progreso={"traduccion": 60})).juzgar(Rol.NINGUNO)
        self.assertTrue(motivos)

    def test_lo_que_la_app_no_lee_no_entra(self):
        motivos = Propuesta().cambiar(PARCHE, lambda p: p.update(progreso="x")).juzgar(Rol.ADMINISTRADOR)
        self.assertTrue(any("progreso" in m for m in motivos), motivos)

    def test_catalogo_a_mano_tras_la_migracion(self):
        for rol in (Rol.COLABORADOR, Rol.ADMINISTRADOR, Rol.PROPIETARIO):
            with self.subTest(rol=rol):
                self.assertEqual([ACTUALIZA_EL_PARCHEADOR],
                                 Propuesta().juzgar(rol, extra=[Cambio(RUTA_CATALOGO, "M")]))
        dueno = Propuesta().juzgar(Rol.DUENO, extra=[Cambio(RUTA_CATALOGO, "M")],
                                   catalogo_despues=particion.texto_json(dict(CATALOGO, versionCatalogo=32)))
        self.assertEqual([], dueno)

    def test_antes_de_la_migracion_solo_el_dueno_crea_los_sueltos(self):
        p = Propuesta(main={"canales/ornizen/canal.json": particion.texto_json(CANAL)})
        p.despues.update(particion.partir(copy.deepcopy(CATALOGO)))
        self.assertIn("migración", p.juzgar(Rol.ADMINISTRADOR)[0])
        self.assertEqual([], p.juzgar(Rol.DUENO))


class Alta(unittest.TestCase):
    def test_un_juego_nuevo_solo_lo_da_de_alta_el_dueno(self):
        for rol in (Rol.COLABORADOR, Rol.EDITOR, Rol.ADMINISTRADOR, Rol.PROPIETARIO):
            with self.subTest(rol=rol):
                motivos = juego_nuevo(Propuesta()).juzgar(rol)
                self.assertTrue(any("del Dueño del programa (PROGRAMA › Juegos)" in m for m in motivos), motivos)
        self.assertEqual([], juego_nuevo(Propuesta()).juzgar(Rol.DUENO))

    def edicion_nueva(self, con_alta=None, quitar_alta=False):
        p = Propuesta().cambiar(JUEGO, lambda j: j["ediciones"].append("gog"))
        edicion = {"esquema": 1, "id": "gog", "nombre": "GOG", "alta": alta() if con_alta is None else con_alta}
        if quitar_alta:
            del edicion["alta"]
        return p.poner("juegos/rance/ediciones/gog.json", edicion)

    def test_alta_de_otra_cuenta_otro_dia_u_otro_canal(self):
        for malo, texto in ((alta(cuenta=1), "alta.cuenta"), (alta(fecha="2026-11-20"), "alta.fecha"),
                            (alta(canal="otro_canal"), "alta.canal"), (alta(cuenta=None), "alta.cuenta")):
            with self.subTest(alta=malo):
                motivos = self.edicion_nueva(malo).juzgar(Rol.ADMINISTRADOR)
                self.assertTrue(any(texto in m for m in motivos), motivos)
        # Un día de margen (zonas horarias).
        for fecha in ("2026-11-23", "2026-11-25"):
            self.assertEqual([], self.edicion_nueva(alta(fecha=fecha)).juzgar(Rol.ADMINISTRADOR))

    def test_alta_que_falta_o_mal_formada(self):
        self.assertTrue(any("le falta `alta`" in m for m in self.edicion_nueva(quitar_alta=True).juzgar(Rol.ADMINISTRADOR)))
        for malo in ({}, {"canal": "ornizen", "cuenta": YO}, {"canal": "ornizen", "cuenta": YO, "fecha": HOY.isoformat(), "x": 1},
                     {"canal": "ORNIZEN", "cuenta": YO, "fecha": "hoy"}, {"canal": "ornizen", "cuenta": True, "fecha": None},
                     {"canal": "ornizen", "cuenta": 2 ** 60, "fecha": None}):
            with self.subTest(alta=malo):
                self.assertTrue(self.edicion_nueva(malo).juzgar(Rol.ADMINISTRADOR))

    def test_un_editor_registra_ediciones_y_un_colaborador_no(self):
        p = Propuesta().cambiar(JUEGO, lambda j: j["ediciones"].append("gog"))
        p.poner("juegos/rance/ediciones/gog.json", {"esquema": 1, "id": "gog", "nombre": "GOG", "alta": alta()})
        self.assertEqual([], p.juzgar(Rol.EDITOR))
        motivos = p.juzgar(Rol.COLABORADOR)
        self.assertTrue(any("alta.canal" in m for m in motivos), motivos)

    def test_el_alta_no_cambia_salvo_el_dueno(self):
        p = Propuesta().cambiar(JUEGO, lambda j: j.update(alta=alta()))
        self.assertTrue(any("`alta`" in m for m in p.juzgar(Rol.PROPIETARIO)))
        self.assertEqual([], p.juzgar(Rol.DUENO))


class LoCentral(unittest.TestCase):
    def test_estado_central_solo_el_dueno(self):
        for estado in ("retirado", "bloqueado"):
            p = Propuesta().cambiar(JUEGO, lambda j: j.update(estado=estado))
            self.assertTrue(any("`estado`" in m for m in p.juzgar(Rol.PROPIETARIO)))
            self.assertEqual([], p.juzgar(Rol.DUENO))
        p = Propuesta().cambiar(JUEGO, lambda j: j.update(estado="cerrado"))
        self.assertTrue(any("activo" in m for m in p.juzgar(Rol.DUENO)))

    def test_la_huella_de_una_edicion_publicada_no_cambia(self):
        p = Propuesta().cambiar(EDICION, lambda e: e["huella"].append({"ruta": "b.dat", "tamano": 1, "hashParcial": HASH, "hash": HASH}))
        self.assertTrue(any("`huella`" in m for m in p.juzgar(Rol.ADMINISTRADOR)))
        self.assertEqual([], p.juzgar(Rol.DUENO))


class Versiones(unittest.TestCase):
    def nueva(self, p, url=URL.replace("1.0.0", "1.1.0")):
        def cambio(parche):
            parche["ediciones"][0]["versiones"].append({"version": "1.1.0", "estado": "pruebas", "fecha": "2026-11-24",
                                                        "paquete": {"url": url, "tamano": 6, "hash": HASH}})
        return p.cambiar(PARCHE, cambio)

    def test_un_editor_sube_una_version(self):
        self.assertEqual([], self.nueva(Propuesta()).juzgar(Rol.EDITOR))

    def test_paquete_fuera_de_los_repositorios_del_canal(self):
        for url in ("https://github.com/otro/repo/releases/download/x/p.zip", "https://example.org/p.zip",
                    f"https://github.com/{REPO}/releases/download/../../x", f"https://github.com/{REPO}/archive/p.zip",
                    f"https://github.com/{REPO}/releases/download/x/p.zip?x=1"):
            with self.subTest(url=url):
                motivos = self.nueva(Propuesta(), url).juzgar(Rol.EDITOR)
                self.assertTrue(any("no está en las Releases" in m for m in motivos), motivos)
        self.assertEqual([], self.nueva(Propuesta(), "https://example.org/p.zip").juzgar(Rol.DUENO))

    def test_retirar_si_borrar_o_reescribir_no(self):
        def retirar(p):
            p["ediciones"][0]["versiones"][0].update(estado="retirada", motivo="fallo", motivoPublico=True,
                                                     fechaRetirada="2026-11-24", notas="otras notas")
        self.assertEqual([], Propuesta().cambiar(PARCHE, retirar).juzgar(Rol.EDITOR))
        motivos = Propuesta().cambiar(PARCHE, lambda p: p["ediciones"][0]["versiones"].clear()).juzgar(Rol.ADMINISTRADOR)
        self.assertTrue(any("no se borran" in m for m in motivos), motivos)
        for campo, valor in (("fecha", "2026-11-02"), ("autor", "otra"), ("paquete", {"url": URL, "tamano": 6, "hash": HASH})):
            with self.subTest(campo=campo):
                motivos = Propuesta().cambiar(PARCHE, lambda p: p["ediciones"][0]["versiones"][0].update({campo: valor})).juzgar(Rol.PROPIETARIO)
                self.assertTrue(any(f"`{campo}`" in m for m in motivos), motivos)
        self.assertEqual([], Propuesta().cambiar(PARCHE, lambda p: p["ediciones"][0]["versiones"].clear()).juzgar(Rol.DUENO))


class Borrados(unittest.TestCase):
    def test_un_parche_con_versiones_no_se_borra(self):
        for rol in (Rol.ADMINISTRADOR, Rol.PROPIETARIO):
            with self.subTest(rol=rol):
                motivos = Propuesta().quitar(PARCHE).juzgar(rol)
                self.assertTrue(any("historial no se borra" in m for m in motivos), motivos)
        self.assertEqual([], Propuesta().quitar(PARCHE).juzgar(Rol.DUENO))

    def test_revertir_un_juego_nuevo_sin_versiones(self):
        main = juego_nuevo(Propuesta()).despues
        p = Propuesta(main=main)
        for ruta in ("juegos/rance-2/juego.json", "juegos/rance-2/ediciones/dl.json", "canales/ornizen/parches/rance-2.json"):
            p.quitar(ruta)
        self.assertEqual([], p.juzgar(Rol.ADMINISTRADOR))

    def test_quitar_una_edicion_que_el_parche_aun_nombra(self):
        p = Propuesta().cambiar(JUEGO, lambda j: j.update(ediciones=[])).quitar(EDICION)
        self.assertTrue(p.juzgar(Rol.EDITOR))

    def test_la_marca_de_migracion_es_programa_parcheador(self):
        main = main_migrado()
        del main["programa/parcheador.json"]
        p = Propuesta(main=main).cambiar(JUEGO, lambda j: j.update(sinopsis="Después"))
        self.assertIn("migración", p.juzgar(Rol.ADMINISTRADOR)[0])


class Coherencia(unittest.TestCase):
    def test_edicion_sin_archivo_o_sin_lista(self):
        p = Propuesta().cambiar(JUEGO, lambda j: j["ediciones"].append("gog"))
        self.assertTrue(any("no tienen su archivo" in m for m in p.juzgar(Rol.ADMINISTRADOR)))
        p = Propuesta().poner("juegos/rance/ediciones/gog.json", {"esquema": 1, "id": "gog", "alta": alta()})
        self.assertTrue(any("no están en la lista" in m for m in p.juzgar(Rol.ADMINISTRADOR)))

    def test_parche_de_un_juego_que_no_existe(self):
        p = Propuesta().poner("canales/ornizen/parches/fantasma.json", {"esquema": 1, "juego": "fantasma"})
        self.assertTrue(any("no existe" in m for m in p.juzgar(Rol.ADMINISTRADOR)))

    def test_borrar_un_juego_con_versiones_es_del_dueno(self):
        # Quitar un juego es de Administrador (reglas del catálogo), pero con versiones publicadas borraría historial.
        p = Propuesta().quitar(JUEGO).quitar(EDICION).quitar(PARCHE)
        self.assertTrue(any("historial no se borra" in m for m in p.juzgar(Rol.ADMINISTRADOR)))
        self.assertEqual([], p.juzgar(Rol.DUENO))
        self.assertTrue(any("quitar un juego" in m for m in p.juzgar(Rol.EDITOR)))

    def test_borrar_el_juego_y_dejar_el_parche(self):
        self.assertTrue(Propuesta().quitar(JUEGO).juzgar(Rol.ADMINISTRADOR))

    def test_nombres_que_no_cuadran(self):
        for ruta, cambio, texto in ((JUEGO, {"id": "otro"}, "nombre de la carpeta"), (EDICION, {"id": "gog"}, "nombre del archivo"),
                                    (PARCHE, {"juego": "otro"}, "nombre del archivo")):
            with self.subTest(ruta=ruta):
                motivos = Propuesta().cambiar(ruta, lambda o: o.update(cambio)).juzgar(Rol.ADMINISTRADOR)
                self.assertTrue(any(texto in m for m in motivos), motivos)


class Forma(unittest.TestCase):
    def test_rutas_que_no_son(self):
        for ruta in ("juegos/rance/portada.png", "juegos/rance/ediciones/sub/x.json", "juegos/../x/juego.json",
                     "juegos/CON/juego.json", "juegos/rance/Juego.json", "canales/ornizen/parches/sub/x.json",
                     "canales/ornizen/parches/rance.txt", "juegos/a b/juego.json"):
            with self.subTest(ruta=ruta):
                motivos = Propuesta().poner(ruta, b"{}").juzgar(Rol.ADMINISTRADOR)
                self.assertTrue(motivos, ruta)

    def test_parche_de_otro_canal(self):
        p = Propuesta().poner("canales/otro_canal/parches/rance.json", {"esquema": 1, "juego": "rance"})
        self.assertTrue(p.juzgar(Rol.ADMINISTRADOR))

    def test_campos_desconocidos_esquema_y_json_estricto(self):
        casos = (
            (JUEGO, lambda j: j.update(huella=HUELLA), "no van aquí"),
            (JUEGO, lambda j: j.update(esquema=2), "`esquema`"),
            (PARCHE, lambda p: p["ediciones"][0].update(huella=HUELLA), "no van en el parche"),
            (PARCHE, lambda p: p["ediciones"].append({"id": "STEAM"}), "repetida"),
            (EDICION, lambda e: e.update(versiones=[]), "no van aquí"),
        )
        for ruta, cambio, texto in casos:
            with self.subTest(texto=texto):
                motivos = Propuesta().cambiar(ruta, cambio).juzgar(Rol.ADMINISTRADOR)
                self.assertTrue(any(texto in m for m in motivos), motivos)
        for datos in (b'{"esquema": 1, "esquema": 1}', b"\xef\xbb\xbf{}", b"[1, 2", b'{"a": NaN}', b"\xff"):
            with self.subTest(datos=datos):
                self.assertTrue(Propuesta().poner(JUEGO, datos).juzgar(Rol.ADMINISTRADOR))

    def test_archivo_enorme(self):
        motivos = Propuesta().poner(JUEGO, b" " * (sueltos.TOPES["juego"] + 1)).juzgar(Rol.ADMINISTRADOR)
        self.assertTrue(any("pesa" in m for m in motivos), motivos)


class Grande(unittest.TestCase):
    def test_un_cambio_pequeno_con_cinco_mil_juegos_en_main(self):
        import time
        catalogo = copy.deepcopy(CATALOGO)
        base = catalogo["juegos"][0]
        catalogo["juegos"] = [dict(copy.deepcopy(base), id=f"juego-{i:05}", orden=i) for i in range(5000)]
        main = particion.partir(catalogo)
        main["canales/ornizen/canal.json"] = particion.texto_json(CANAL)
        inicio = time.monotonic()
        p = Propuesta(main).cambiar("juegos/juego-04999/juego.json", lambda j: j.update(sinopsis="Nueva"))
        self.assertEqual([], p.juzgar(Rol.COLABORADOR))
        self.assertLess(time.monotonic() - inicio, 60)


class LecturaConGit(unittest.TestCase):
    def test_archivos_sueltos_de_un_commit(self):
        import os
        import subprocess
        import tempfile
        import permisos as permisos_mod
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = pathlib.Path(carpeta)
            archivos = main_migrado()
            archivos["juegos/rance/LEEME.md"] = b"no se lee"
            archivos["canales/ornizen/miembros.json"] = b"{}"
            archivos["juegos/enorme/juego.json"] = b" " * (sueltos.TOPES["juego"] + 10)
            for ruta, datos in archivos.items():
                (raiz / ruta).parent.mkdir(parents=True, exist_ok=True)
                (raiz / ruta).write_bytes(datos)
            entorno = dict(os.environ, GIT_AUTHOR_NAME="x", GIT_AUTHOR_EMAIL="x@x", GIT_COMMITTER_NAME="x",
                           GIT_COMMITTER_EMAIL="x@x")
            for orden in (["init", "-q"], ["config", "core.autocrlf", "false"], ["add", "-A"], ["commit", "-qm", "x"]):
                subprocess.run(["git", *orden], cwd=raiz, check=True, env=entorno, capture_output=True)
            antes = os.getcwd()
            os.chdir(raiz)
            try:
                leidos = permisos_mod.archivos_sueltos("HEAD")
            finally:
                os.chdir(antes)
        esperados = {r: d for r, d in archivos.items() if sueltos.es_suelto(r) or r.endswith("/canal.json")}
        self.assertEqual(set(esperados), set(leidos))
        for ruta, datos in esperados.items():
            if ruta == "juegos/enorme/juego.json":
                self.assertEqual(sueltos.TOPES["juego"] + 1, len(leidos[ruta]))
            else:
                self.assertEqual(datos, leidos[ruta], ruta)


if __name__ == "__main__":
    unittest.main()


class Programa(unittest.TestCase):
    def test_un_administrador_cambia_el_grupo_y_nada_mas_de_programa(self):
        p = Propuesta().cambiar("programa/parcheador.json", lambda x: x.update(grupo={"nombre": "Otro grupo"}))
        self.assertEqual([], p.juzgar(Rol.ADMINISTRADOR))
        self.assertTrue(p.juzgar(Rol.EDITOR))
        p = Propuesta().cambiar("programa/parcheador.json", lambda x: x["launcher"].update(ultimaVersion="9.9.9"))
        self.assertTrue(any("Dueño" in m for m in p.juzgar(Rol.PROPIETARIO)))
        self.assertEqual([], p.juzgar(Rol.DUENO))
        p = Propuesta().cambiar("programa/parcheador.json", lambda x: x.update(grupo={"nombre": "x"}, otra=1))
        self.assertTrue(p.juzgar(Rol.ADMINISTRADOR))
        # Quitar el archivo o crearlo de nuevo sigue siendo del Dueño.
        self.assertTrue(Propuesta().quitar("programa/parcheador.json").juzgar(Rol.ADMINISTRADOR))

    def test_normas_etiquetas_solo_el_dueno(self):
        p = Propuesta().cambiar("normas/etiquetas.json", lambda x: x.update(etiquetas=[]))
        self.assertTrue(p.juzgar(Rol.PROPIETARIO))
        self.assertEqual([], p.juzgar(Rol.DUENO))
