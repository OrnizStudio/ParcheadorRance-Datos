"""Pruebas de las reglas del robot.  Uso:  python -m unittest discover -s robot/pruebas"""
import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from permisos import Cambio, Permisos, Rol, RUTA_CATALOGO, comprobar  # noqa: E402

HASH = "blake3:" + "a" * 64
BASE = {
    "esquema": 1, "versionCatalogo": 5,
    "launcher": {"ultimaVersion": "0.1.0"},
    "grupo": {"nombre": "Grupo"},
    "etiquetas": [{"id": "beta", "nombre": "Beta"}, {"id": "adultos", "nombre": "+18"}],
    "juegos": [{
        "id": "juego1", "habilitado": True, "pruebas": False, "orden": 1, "titulo": "Juego 1",
        "estado": "en_progreso", "progreso": {"traduccion": 10, "revision": 0, "imagenes": 0},
        "sinopsis": "Antes", "etiquetas": ["beta"], "creditos": [{"rol": "Traducción", "personas": ["A"]}],
        "ediciones": [{"id": "steam", "nombre": "Steam", "notaEdicion": "", "contenido": {"texto": True},
                       "huella": []}],
        "parche": {"version": "1.0.0", "notas": "Primera", "pruebas": True,
                   "paquetes": [{"edicion": "steam", "url": "https://example.org/p.zip", "tamano": 10, "hash": HASH}]},
    }],
}
ADMIN, EDITOR, COLABORADOR, NADIE = (Permisos(r) for r in (Rol.ADMINISTRADOR, Rol.EDITOR, Rol.COLABORADOR, Rol.NINGUNO))
PROPIETARIO = Permisos(Rol.DUENO)


def catalogo(cambiar=None, subir_version=True):
    nuevo = copy.deepcopy(BASE)
    if subir_version:
        nuevo["versionCatalogo"] += 1
    if cambiar:
        cambiar(nuevo)
    return nuevo


def revisar(permisos, cambiar=None, subir_version=True, archivos=()):
    despues = catalogo(cambiar, subir_version)
    cambios = [Cambio(RUTA_CATALOGO, "M")] if despues != BASE else []
    return comprobar(cambios + list(archivos), json.dumps(BASE), json.dumps(despues), permisos)


def juego(c):
    return c["juegos"][0]


class General(unittest.TestCase):
    def test_sin_rol_se_rechaza(self):
        motivos = revisar(NADIE, lambda c: juego(c).update(sinopsis="x"))
        self.assertEqual(1, len(motivos))
        self.assertIn("no tiene ningún rol", motivos[0])

    def test_la_version_tiene_que_subir_tambien_para_un_administrador(self):
        motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(BASE),
                            json.dumps(catalogo(lambda c: juego(c).update(sinopsis="x"), subir_version=False)), ADMIN)
        self.assertEqual(1, len(motivos))
        self.assertIn("`versionCatalogo` tiene que subir", motivos[0])

    def test_json_roto(self):
        motivos = comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(BASE), '{ "esquema": 1, ', ADMIN)
        self.assertIn("no es un JSON válido", motivos[0])

    def test_borrar_el_catalogo(self):
        self.assertIn("No se puede borrar", comprobar([Cambio(RUTA_CATALOGO, "D")], json.dumps(BASE), None, ADMIN)[0])

    def test_etiqueta_que_no_existe(self):
        motivos = revisar(COLABORADOR, lambda c: juego(c).update(etiquetas=["inventada"]))
        self.assertTrue(any("no existe" in m for m in motivos))

    def test_paquete_sin_https_o_con_hash_malo(self):
        def cambiar(c):
            juego(c)["parche"]["paquetes"][0].update(url="http://example.org/p.zip", hash="sha1:123")
        self.assertEqual(2, len(revisar(ADMIN, cambiar)))

    def test_enlace_simbolico(self):
        motivos = comprobar([Cambio("catalogo/juegos/juego1/icono.png", "A", "120000")],
                            json.dumps(BASE), json.dumps(BASE), ADMIN)
        self.assertIn("enlaces simbólicos", motivos[0])

    def test_primer_catalogo_sin_uno_anterior(self):
        self.assertEqual([], comprobar([Cambio(RUTA_CATALOGO, "A")], None, json.dumps(BASE), ADMIN))


class Administrador(unittest.TestCase):
    def test_puede_todo(self):
        def cambiar(c):
            c["juegos"].append({"id": "juego2", "habilitado": True})
            c["launcher"]["versionMinima"] = "0.2.0"
            juego(c).update(pruebas=True, habilitado=False, etiquetas=["beta", "adultos"])
        archivos = [Cambio("README.md", "M"), Cambio("pruebas/crear-juego-prueba.py", "M"),
                    Cambio("catalogo/juegos/juego2/banner.jpg", "A", tamano=100)]
        self.assertEqual([], revisar(ADMIN, cambiar, archivos=archivos))

    def test_no_crea_edita_ni_borra_etiquetas_del_catalogo(self):
        cambios = {
            "crear": lambda c: c["etiquetas"].append({"id": "nueva", "nombre": "Nueva"}),
            "editar": lambda c: c["etiquetas"][0].update(nombre="Beta abierta", color="ambar"),
            "borrar": lambda c: c["etiquetas"].pop(),
        }
        for que, cambiar in cambios.items():
            with self.subTest(que):
                motivos = revisar(ADMIN, cambiar)
                self.assertEqual(1, len(motivos), motivos)
                self.assertIn("solo las crea, edita o borra el Dueño del programa", motivos[0])

    def test_pone_y_quita_en_un_juego_etiquetas_que_ya_existen(self):
        self.assertEqual([], revisar(ADMIN, lambda c: juego(c).update(etiquetas=["adultos"])))
        self.assertEqual([], revisar(ADMIN, lambda c: juego(c)["ediciones"][0].update(etiquetas=["beta"])))


class Propietario(unittest.TestCase):
    def test_crea_edita_y_borra_etiquetas_del_catalogo(self):
        self.assertEqual([], revisar(PROPIETARIO, lambda c: c["etiquetas"].append({"id": "nueva", "nombre": "Nueva"})))
        self.assertEqual([], revisar(PROPIETARIO, lambda c: c["etiquetas"][0].update(nombre="Beta abierta")))
        # «adultos» no la lleva ningún juego: se puede borrar. (Borrar una que se usa lo para la validación
        # general: «la etiqueta no existe en el catálogo».)
        self.assertEqual([], revisar(PROPIETARIO, lambda c: c["etiquetas"].pop()))
        motivos = revisar(PROPIETARIO, lambda c: c["etiquetas"].pop(0))
        self.assertTrue(any("la etiqueta `beta` no existe" in m for m in motivos), motivos)

    def test_tambien_todo_lo_de_un_administrador(self):
        def cambiar(c):
            c["juegos"].append({"id": "juego2", "habilitado": True})
            c["launcher"]["versionMinima"] = "0.2.0"
            c["etiquetas"].append({"id": "nueva"})
        self.assertEqual([], revisar(PROPIETARIO, cambiar))


class Editor(unittest.TestCase):
    def test_contenido_de_un_juego_que_ya_existe(self):
        def cambiar(c):
            j = juego(c)
            j["ediciones"].append({"id": "gog", "nombre": "GOG"})
            j["parche"].update(version="1.1.0", pruebas=False)
            j["creditos"] = []
            j["titulo"] = "Otro título"
            j["orden"] = 3
        archivos = [Cambio("catalogo/juegos/juego1/banner.jpg", "M", tamano=200_000),
                    Cambio("catalogo/juegos/juego1/viejo.png", "D")]
        self.assertEqual([], revisar(EDITOR, cambiar, archivos=archivos))

    def test_no_da_de_alta_juegos(self):
        motivos = revisar(EDITOR, lambda c: c["juegos"].append({"id": "juego2"}),
                          archivos=[Cambio("catalogo/juegos/juego2/icono.png", "A", tamano=10)])
        self.assertTrue(any("Juego nuevo `juego2`" in m for m in motivos))
        self.assertTrue(any("todavía no existe" in m for m in motivos))

    def test_no_quita_juegos(self):
        self.assertTrue(any("quitar un juego" in m for m in revisar(EDITOR, lambda c: c["juegos"].clear())))

    def test_no_publica_ni_oculta_juegos(self):
        self.assertEqual(1, len(revisar(EDITOR, lambda c: juego(c).update(pruebas=True))))
        self.assertEqual(1, len(revisar(EDITOR, lambda c: juego(c).update(habilitado=False))))

    def test_no_toca_parcheador_grupo_ni_etiquetas(self):
        valores = {"launcher": {"ultimaVersion": "9.0.0"}, "grupo": {"nombre": "otro"}, "esquema": 2,
                   "etiquetas": [{"id": "beta"}, {"id": "adultos"}, {"id": "x"}]}
        for clave, valor in valores.items():
            with self.subTest(clave):
                motivos = revisar(EDITOR, lambda c: c.update({clave: valor}))
                self.assertEqual(1, len(motivos), motivos)
                self.assertIn("el Dueño del programa" if clave == "etiquetas" else "solo la cambia un Administrador", motivos[0])

    def test_no_toca_el_robot_ni_otros_archivos(self):
        for ruta in ("README.md", "equipo.json", "catalogo/otro.json"):
            with self.subTest(ruta):
                motivos = revisar(EDITOR, archivos=[Cambio(ruta, "M")], subir_version=False)
                self.assertIn("solo lo puede cambiar un Administrador", motivos[0])
        for ruta in (".github/workflows/permisos.yml", "robot/permisos.py"):
            with self.subTest(ruta):
                motivos = revisar(EDITOR, archivos=[Cambio(ruta, "M")], subir_version=False)
                self.assertIn("solo lo cambia el Dueño del programa", motivos[0])

    def test_solo_imagenes_y_no_enormes(self):
        exe = revisar(EDITOR, archivos=[Cambio("catalogo/juegos/juego1/a.exe", "A", tamano=1)], subir_version=False)
        self.assertIn("solo van imágenes", exe[0])
        grande = revisar(EDITOR, archivos=[Cambio("catalogo/juegos/juego1/a.png", "A", tamano=9_000_000)], subir_version=False)
        self.assertIn("máximo", grande[0])


class Colaborador(unittest.TestCase):
    def test_textos_etiquetas_y_estado(self):
        def cambiar(c):
            j = juego(c)
            j.update(sinopsis="Después", etiquetas=["beta", "adultos"], estado="en_revision",
                     progreso={"traduccion": 50, "revision": 5, "imagenes": 0})
            j["parche"]["notas"] = "Notas nuevas"
            j["ediciones"][0].update(notaEdicion="Nota", contenido={"texto": True, "imagenes": True}, etiquetas=["beta"])
        self.assertEqual([], revisar(COLABORADOR, cambiar))

    def test_nada_mas(self):
        casos = {
            "creditos": lambda c: juego(c).update(creditos=[]),
            "titulo": lambda c: juego(c).update(titulo="x"),
            "parche.version": lambda c: juego(c)["parche"].update(version="2.0.0"),
            "parche.pruebas": lambda c: juego(c)["parche"].update(pruebas=False),
            "parche.paquetes": lambda c: juego(c)["parche"]["paquetes"][0].update(tamano=11),
            "edición nueva": lambda c: juego(c)["ediciones"].append({"id": "gog"}),
            "edición quitada": lambda c: juego(c)["ediciones"].clear(),
            "huella": lambda c: juego(c)["ediciones"][0].update(huella=[{"ruta": "a"}]),
            "habilitado": lambda c: juego(c).update(habilitado=False),
            "crear o quitar": lambda c: juego(c).pop("parche"),
        }
        for nombre, cambiar in casos.items():
            with self.subTest(nombre):
                motivos = revisar(COLABORADOR, cambiar)
                self.assertEqual(1, len(motivos), motivos)
                self.assertIn(nombre, motivos[0])
                self.assertIn("un Colaborador solo puede", motivos[0])

    def test_no_sube_imagenes(self):
        motivos = revisar(COLABORADOR, archivos=[Cambio("catalogo/juegos/juego1/banner.jpg", "M", tamano=10)], subir_version=False)
        self.assertIn("las cambian los Editores", motivos[0])

    def test_no_crea_etiquetas(self):
        motivos = revisar(COLABORADOR, lambda c: c["etiquetas"].append({"id": "nueva"}))
        self.assertIn("no las crean", motivos[0])


class RolesPorJuego(unittest.TestCase):
    """Preparado para los futuros líderes por juego: el rol se pregunta juego a juego."""

    def test_un_colaborador_con_rol_de_editor_en_un_juego(self):
        lider = Permisos(Rol.COLABORADOR, {"juego1": Rol.EDITOR})
        self.assertEqual([], revisar(lider, lambda c: juego(c).update(titulo="x"),
                                     archivos=[Cambio("catalogo/juegos/juego1/banner.jpg", "M", tamano=10)]))
        self.assertEqual(1, len(revisar(lider, lambda c: c["juegos"].append({"id": "juego2"}))))

    def test_cuenta_el_menor_de_dos_personas(self):
        self.assertEqual(Rol.COLABORADOR, ADMIN.el_menor(COLABORADOR).rol_global)


if __name__ == "__main__":
    unittest.main()


class SoloDelPropietario(unittest.TestCase):
    """`normas/`, `robot/` y `.github/` solo los cambia el Propietario, ni siquiera un Administrador."""
    RUTAS = ["normas/archivos-prohibidos.json", "normas/propietario.json", "normas/nueva.json",
             "robot/permisos.py", "robot/pruebas/test_permisos.py", "robot/requisitos.txt",
             ".github/workflows/permisos.yml", ".github/workflows/nuevo.yml", ".github/CODEOWNERS",
             "Robot/permisos.py", ".GITHUB/workflows/x.yml"]
    PROPIETARIO = Permisos(Rol.DUENO)

    def proponer(self, permisos, ruta, estado="M"):
        return comprobar([Cambio(ruta, estado)], json.dumps(BASE), json.dumps(BASE), permisos)

    def test_un_administrador_no_puede_cambiarlos_ni_borrarlos(self):
        for ruta in self.RUTAS:
            for estado in ("A", "M", "D"):
                with self.subTest(ruta=ruta, estado=estado):
                    motivos = self.proponer(ADMIN, ruta, estado)
                    self.assertEqual(1, len(motivos))
                    self.assertIn("solo lo cambia el Dueño del programa", motivos[0])

    def test_los_demas_roles_tampoco(self):
        for permisos in (EDITOR, COLABORADOR):
            for ruta in ("robot/permisos.py", ".github/workflows/permisos.yml", "normas/propietario.json"):
                with self.subTest(rol=permisos.rol_global, ruta=ruta):
                    self.assertIn("solo lo cambia el Dueño del programa", self.proponer(permisos, ruta)[0])

    def test_el_propietario_si(self):
        for ruta in self.RUTAS:
            with self.subTest(ruta=ruta):
                self.assertEqual([], self.proponer(self.PROPIETARIO, ruta))

    def test_si_un_administrador_sube_un_cambio_a_la_propuesta_del_propietario_cuenta_el_administrador(self):
        self.assertIn("solo lo cambia el Dueño del programa",
                      self.proponer(self.PROPIETARIO.el_menor(ADMIN), "robot/permisos.py")[0])

    def test_el_mensaje_dice_que_carpeta_es(self):
        self.assertIn("el robot de permisos (`robot/`)", self.proponer(ADMIN, "robot/permisos.py")[0])
        self.assertIn("(`.github/`)", self.proponer(ADMIN, ".github/workflows/permisos.yml")[0])
        self.assertIn("canales/<canal>/lista-negra.json", self.proponer(ADMIN, "normas/archivos-prohibidos.json")[0])

    def test_lo_demas_fuera_de_catalogo_sigue_siendo_del_administrador(self):
        for ruta in ("README.md", "pruebas/crear-juego-prueba.py", "robots.txt", "normas.md", "github/x.yml"):
            with self.subTest(ruta=ruta):
                self.assertEqual([], self.proponer(ADMIN, ruta))
