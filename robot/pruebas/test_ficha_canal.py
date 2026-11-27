"""La ficha pública de cada canal (`canales/<c>/ficha.json`, docs/canales.md §1.4): qué vale, quién la cambia y qué
publica el robot en `canales/<xx>.json` para la ficha de la app (0.4.3).

Casos extremos: textos al tope y uno más, Unicode que engaña (bidi, anchura cero, alfabetos mezclados), direcciones
que no son lo que parecen, listas vacías y llenas, JSON con trampas y equipos enormes.
"""

import datetime
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import canales  # noqa: E402
import particion  # noqa: E402
import publicar  # noqa: E402
from permisos import Rol  # noqa: E402
from test_fase_d_canales import OTRO, de, juzgar, main_con_dos_canales  # noqa: E402
from test_fase_d_publicar import con_miembros, miembro  # noqa: E402
from test_particion import todo_el_modelo  # noqa: E402
from test_publicado_app import canal_de, canal_json, con_canales, publicados  # noqa: E402
from test_publicar import sueltos_de  # noqa: E402
from test_sueltos import Propuesta  # noqa: E402

HOY = datetime.date(2026, 11, 24)
RUTA = f"canales/{OTRO}/ficha.json"


def ficha(**campos):
    """Una ficha llena y válida, como la escribe el parcheador; `campos` cambia o quita (None) lo que haga falta."""
    objeto = {
        "esquema": 1,
        "descripcion": "Traducimos al español la saga Rance desde 2019.\nSomos cinco.",
        "idiomas": ["es"],
        "tipos": ["completa", "mod"],
        "enlaces": [{"tipo": "discord", "texto": "Discord", "url": "https://discord.gg/rance"},
                    {"tipo": "web", "texto": "Web", "url": "https://rance-es.org/"}],
        "enCurso": [{"nombre": "Rance X: Kessen", "tipo": "completa", "progreso": 72, "actualizado": "2026-11-24"}],
        "destacado": "rance",
    }
    for clave, valor in campos.items():
        if valor is None:
            objeto.pop(clave, None)
        else:
            objeto[clave] = valor
    return objeto


def errores(objeto):
    return canales.validar_ficha(objeto, RUTA, HOY)


def proyecto(nombre="Proyecto", tipo="parcial", progreso=10, actualizado="2026-11-20"):
    return {"nombre": nombre, "tipo": tipo, "progreso": progreso, "actualizado": actualizado}


def enlace(url="https://ejemplo.org/", texto="Web", tipo="web"):
    return {"tipo": tipo, "texto": texto, "url": url}


class QueVale(unittest.TestCase):
    def test_llena_y_minima(self):
        self.assertEqual([], errores(ficha()))
        self.assertEqual([], errores({"esquema": 1}))
        self.assertEqual([], errores(ficha(destacado=None, enlaces=[], enCurso=[], idiomas=[], tipos=[], descripcion="")))

    def test_esquema_y_campos_desconocidos(self):
        self.assertTrue(any("esquema" in e for e in errores(ficha(esquema=2))))
        self.assertTrue(any("`novedades` no existe" in e for e in errores(ficha(novedades=[]))))
        for raro in ([], "texto", 1, None):
            with self.subTest(raro):
                self.assertTrue(errores(raro))

    def test_descripcion_al_tope(self):
        self.assertEqual([], errores(ficha(descripcion="a" * 500)))
        self.assertTrue(any("501 caracteres" in e for e in errores(ficha(descripcion="a" * 501))))
        # Grafemas, no puntos de código: una letra con su marca combinada cuenta una vez… pero tiene que ir en NFC.
        self.assertEqual([], errores(ficha(descripcion="ñ" * 500)))
        self.assertTrue(any("NFC" in e for e in errores(ficha(descripcion="ñ"))))
        self.assertEqual([], errores(ficha(descripcion="🎌" * 500)))
        self.assertEqual([], errores(ficha(descripcion="a\nb\nc\nd")))
        self.assertTrue(any("saltos" in e for e in errores(ficha(descripcion="a\nb\nc\nd\ne"))))

    def test_descripcion_que_engana(self):
        for texto, que in (("Hola‮olleh", "dirección"), ("Ho​la", "invisible"), ("Ho\x07la", "control"),
                           (" Hola", "espacios"), ("Hola ", "espacios"), ("Rаnce", "alfabetos"), (5, "texto")):
            with self.subTest(texto=texto):
                self.assertTrue(any(que in e for e in errores(ficha(descripcion=texto))), errores(ficha(descripcion=texto)))
        # Un texto en un solo alfabeto que no es el latino sí vale (un grupo ruso o japonés).
        self.assertEqual([], errores(ficha(descripcion="Переводим игры")))
        self.assertEqual([], errores(ficha(descripcion="ランスの翻訳")))

    def test_idiomas_y_tipos(self):
        self.assertEqual([], errores(ficha(idiomas=list(canales.IDIOMAS_FICHA[:8]))))
        for malo in (list(canales.IDIOMAS_FICHA[:9]), ["es", "es"], ["xx"], ["ES"], "es", [1], [None]):
            with self.subTest(malo):
                self.assertTrue(any("`idiomas`" in e for e in errores(ficha(idiomas=malo))))
        self.assertEqual([], errores(ficha(tipos=["completa", "parcial", "mod"])))
        for malo in (["mods"], ["mod", "mod"], "mod", [True]):
            with self.subTest(malo):
                self.assertTrue(any("`tipos`" in e for e in errores(ficha(tipos=malo))))


class Enlaces(unittest.TestCase):
    def test_cuatro_si_cinco_no(self):
        cuatro = [enlace(f"https://e{i}.org/") for i in range(4)]
        self.assertEqual([], errores(ficha(enlaces=cuatro)))
        self.assertTrue(any("como mucho 4" in e for e in errores(ficha(enlaces=cuatro + [enlace("https://e9.org/")]))))
        self.assertTrue(errores(ficha(enlaces={"url": "https://e.org/"})))

    def test_direcciones_que_valen(self):
        for url in ("https://discord.gg/abc", "https://ko-fi.com/rance?x=1&y=2#arriba", "https://sub.dominio.co.uk/a/b",
                    "https://xn--espaol-zwa.org/", "https://ejemplo.org:443/", "https://e.org/%C3%B1", "https://e.org",
                    "https://mega.nz/folder/AbC#clave"):
            with self.subTest(url):
                self.assertEqual([], errores(ficha(enlaces=[enlace(url)])))

    def test_direcciones_que_no(self):
        for url, que in (("http://e.org/", "https://"), ("javascript:alert(1)", "https://"), ("HTTPS://e.org/", "https://"),
                         ("https://usuario:clave@e.org/", "usuario"), ("https://e.org@malo.com/", "usuario"),
                         ("https://e.org:8080/", "puerto"), ("https://e.org:/", "puerto"),
                         ("https://127.0.0.1/", "sitio"), ("https://localhost/", "sitio"), ("https://[::1]/", ""),
                         ("https://españa.org/", "sitio"), ("https://E.org/", "sitio"), ("https:///camino", "sitio"),
                         ("https://e.org/a b", "espacios"), ("https://e.org/ñ", "espacios"), ("https://e.org/\n", "espacios"),
                         ("https://e.org\\@malo.com/", ""), ("https://e.org/" + "a" * 300, "300"),
                         ("https://-e.org/", "sitio"), ("https://e.123/", "sitio"), (None, "texto"), (42, "texto")):
            with self.subTest(url):
                motivos = errores(ficha(enlaces=[enlace(url)]))
                self.assertTrue(any("`url`" in e and que in e for e in motivos), motivos)

    def test_texto_tipo_y_repetidos(self):
        self.assertEqual([], errores(ficha(enlaces=[enlace(texto="x" * 40)])))
        for malo, que in ((enlace(texto="x" * 41), "41"), (enlace(texto=""), "vacío"), (enlace(texto="a\nb"), "saltos"),
                          (enlace(tipo="twitter"), "`tipo`"), (dict(enlace(), icono="x"), "`icono` no existe"),
                          ({"url": "https://e.org/"}, "`tipo`"), ("https://e.org/", "tiene que ser")):
            with self.subTest(malo):
                self.assertTrue(any(que in e for e in errores(ficha(enlaces=[malo]))), errores(ficha(enlaces=[malo])))
        repetidos = [enlace("https://e.org/a"), enlace("https://e.org/a", texto="Otra")]
        self.assertTrue(any("repetida" in e for e in errores(ficha(enlaces=repetidos))))
        # Un camino con otras mayúsculas es otra dirección (las invitaciones de Discord las distinguen).
        self.assertEqual([], errores(ficha(enlaces=[enlace("https://discord.gg/AbC"), enlace("https://discord.gg/abc")])))


class EnCurso(unittest.TestCase):
    def test_cinco_si_seis_no(self):
        cinco = [proyecto(f"P{i}") for i in range(5)]
        self.assertEqual([], errores(ficha(enCurso=cinco)))
        self.assertTrue(any("como mucho 5" in e for e in errores(ficha(enCurso=cinco + [proyecto("P9")]))))

    def test_nombres(self):
        self.assertEqual([], errores(ficha(enCurso=[proyecto("x" * 60)])))
        self.assertTrue(any("61" in e for e in errores(ficha(enCurso=[proyecto("x" * 61)]))))
        self.assertTrue(any("vacío" in e for e in errores(ficha(enCurso=[proyecto("")]))))
        # Repetido sin distinguir mayúsculas, pero «Rance 01» y «Rance 02» son dos proyectos.
        self.assertTrue(any("ya está" in e for e in errores(ficha(enCurso=[proyecto("Rance 01"), proyecto("RANCE 01")]))))
        self.assertEqual([], errores(ficha(enCurso=[proyecto("Rance 01"), proyecto("Rance 02")])))

    def test_progreso(self):
        for bueno in (0, 100, 50):
            self.assertEqual([], errores(ficha(enCurso=[proyecto(progreso=bueno)])))
        for malo in (-1, 101, 72.5, True, "72", None, 10 ** 30):
            with self.subTest(malo):
                self.assertTrue(any("`progreso`" in e for e in errores(ficha(enCurso=[proyecto(progreso=malo)]))))

    def test_fechas(self):
        self.assertEqual([], errores(ficha(enCurso=[proyecto(actualizado="2026-11-25")])))  # un día de margen
        self.assertEqual([], errores(ficha(enCurso=[proyecto(actualizado="2001-01-01")])))  # muy vieja: «sin actualizar»
        self.assertTrue(any("futura" in e for e in errores(ficha(enCurso=[proyecto(actualizado="2026-11-26")]))))
        for mala in ("2026-02-30", "24/11/2026", "2026-11-24T10:00", "2026-11-24\n", None):
            with self.subTest(mala):
                self.assertTrue(any("aaaa-mm-dd" in e for e in errores(ficha(enCurso=[proyecto(actualizado=mala)]))))

    def test_tipo_y_campos(self):
        self.assertTrue(any("`tipo`" in e for e in errores(ficha(enCurso=[proyecto(tipo="mods")]))))
        self.assertTrue(any("no existe" in e for e in errores(ficha(enCurso=[dict(proyecto(), autor="x")]))))
        self.assertTrue(errores(ficha(enCurso=["Rance X"])))


class Destacado(unittest.TestCase):
    def test_formato(self):
        for bueno in ("rance", "rance-x", "Rance_01.v2", None):
            self.assertEqual([], errores(ficha(destacado=bueno)) if bueno else errores(ficha(destacado=None)))
        for malo in ("../rance", "rance/", "", "-rance", "rance\n", 3, ["rance"], "a" * 101):
            with self.subTest(malo):
                self.assertTrue(any("`destacado`" in e for e in errores(ficha(destacado=malo))))


class Propuestas(unittest.TestCase):
    def test_un_administrador_la_crea_cambia_y_borra(self):
        for rol in (Rol.ADMINISTRADOR, Rol.PROPIETARIO):
            with self.subTest(rol):
                p = Propuesta(main_con_dos_canales()).poner(RUTA, ficha())
                self.assertEqual([], juzgar(p, de({OTRO: rol})))
        main = main_con_dos_canales()
        main[RUTA] = particion.texto_json(ficha())
        self.assertEqual([], juzgar(Propuesta(main).poner(RUTA, ficha(descripcion="Otra")), de({OTRO: Rol.ADMINISTRADOR})))
        self.assertEqual([], juzgar(Propuesta(main).quitar(RUTA), de({OTRO: Rol.ADMINISTRADOR})))

    def test_ni_editores_ni_colaboradores_ni_de_fuera(self):
        for rol in (Rol.EDITOR, Rol.COLABORADOR):
            with self.subTest(rol):
                motivos = juzgar(Propuesta(main_con_dos_canales()).poner(RUTA, ficha()), de({OTRO: rol}))
                self.assertTrue(any("la cambia un Administrador" in m for m in motivos), motivos)
        motivos = juzgar(Propuesta(main_con_dos_canales()).poner(RUTA, ficha()), de({}))
        self.assertTrue(motivos)
        # Un administrador de otro canal tampoco.
        motivos = juzgar(Propuesta(main_con_dos_canales()).poner(RUTA, ficha()), de({"ornizen": Rol.PROPIETARIO}))
        self.assertTrue(motivos)

    def test_el_destacado_tiene_que_tener_parche_del_canal(self):
        # `rance-x` solo lo tiene el canal oficial.
        motivos = juzgar(Propuesta(main_con_dos_canales()).poner(RUTA, ficha(destacado="rance-x")),
                         de({OTRO: Rol.ADMINISTRADOR}))
        self.assertTrue(any("no es un juego con parche de @rance_es" in m for m in motivos), motivos)
        # Si la misma propuesta quita el parche, tampoco.
        p = Propuesta(main_con_dos_canales()).poner(RUTA, ficha()).quitar(f"canales/{OTRO}/parches/rance.json")
        self.assertTrue(any("no es un juego con parche" in m for m in juzgar(p, de({OTRO: Rol.PROPIETARIO}))))

    def test_mismo_contenido_con_otro_formato(self):
        main = main_con_dos_canales()
        main[RUTA] = particion.texto_json(ficha())
        p = Propuesta(main).poner(RUTA, json.dumps(ficha(), ensure_ascii=False).encode())
        self.assertTrue(any("no cambia nada" in m for m in juzgar(p, de({OTRO: Rol.ADMINISTRADOR}))))

    def test_json_con_trampas(self):
        for datos, que in ((b'{"esquema": 1, "esquema": 1}', "repet"), (b'{"esquema": 1, "enCurso": [{"progreso": NaN}]}', ""),
                           (b"{", ""), (b"\xff\xfe{}", ""), (b'{"esquema": 1}' + b" " * (16 * 1024), "KB"),
                           (("[" * 40 + "]" * 40).encode(), "")):
            with self.subTest(datos[:30]):
                motivos = juzgar(Propuesta(main_con_dos_canales()).poner(RUTA, datos), de({OTRO: Rol.ADMINISTRADOR}))
                self.assertTrue(motivos and any(que in m for m in motivos), motivos)

    def test_los_errores_salen_todos_de_una_vez(self):
        mala = ficha(descripcion="a" * 501, enlaces=[enlace("http://e.org/")], enCurso=[proyecto(progreso=140)])
        motivos = juzgar(Propuesta(main_con_dos_canales()).poner(RUTA, mala), de({OTRO: Rol.ADMINISTRADOR}))
        for que in ("`descripcion`", "`url`", "`progreso`"):
            self.assertTrue(any(que in m for m in motivos), (que, motivos))

    def test_otro_archivo_en_la_carpeta_lo_dice(self):
        motivos = juzgar(Propuesta(main_con_dos_canales()).poner(f"canales/{OTRO}/novedades.json", {"esquema": 1}),
                         de({OTRO: Rol.PROPIETARIO}))
        self.assertTrue(any("`ficha.json`" in m for m in motivos), motivos)


def con_ficha(archivos, cid, objeto):
    archivos = dict(archivos)
    archivos[f"canales/{cid}/ficha.json"] = objeto if isinstance(objeto, bytes) else particion.texto_json(objeto)
    return archivos


class Publicacion(unittest.TestCase):
    def test_la_ficha_llega_a_canales(self):
        archivos = con_ficha(con_canales(sueltos_de(), "rance_es"), "ornizen", ficha(destacado="rance-x"))
        canal = canal_de(publicados(archivos, todo_el_modelo()), "ornizen")
        esperada = {k: v for k, v in ficha(destacado="rance-x").items() if k != "esquema"}
        self.assertEqual(esperada, canal["ficha"])
        self.assertEqual("2026-11-21", canal["creado"])
        self.assertIsNone(canal_de(publicados(archivos, todo_el_modelo()), "rance_es")["ficha"])

    def test_lo_que_falta_sale_vacio(self):
        canal = canal_de(publicados(con_ficha(con_canales(sueltos_de()), "ornizen", {"esquema": 1}), todo_el_modelo()),
                         "ornizen")
        self.assertEqual({"descripcion": "", "idiomas": [], "tipos": [], "enlaces": [], "enCurso": [], "destacado": None},
                         canal["ficha"])

    def test_un_destacado_sin_parche_publicado_sale_null(self):
        # `rance` no tiene parche del canal oficial en estos archivos (y uno inventado tampoco).
        for destacado in ("rance", "no-existe"):
            with self.subTest(destacado):
                archivos = con_ficha(con_canales(sueltos_de()), "ornizen", ficha(destacado=destacado))
                self.assertIsNone(canal_de(publicados(archivos, todo_el_modelo()), "ornizen")["ficha"]["destacado"])

    def test_una_ficha_que_no_vale_no_sale_y_no_tumba_nada(self):
        for mala in (b"{", ficha(enlaces=[enlace("javascript:alert(1)")]), b'{"esquema": 1}' + b" " * (17 * 1024)):
            with self.subTest(str(mala)[:30]):
                salida = publicados(con_ficha(con_canales(sueltos_de()), "ornizen", mala), todo_el_modelo())
                canal = canal_de(salida, "ornizen")
                self.assertIsNone(canal["ficha"])
                self.assertEqual("Ornizen", canal["nombre"])

    def test_el_equipo_por_rol_sin_invitados(self):
        archivos = con_miembros(con_canales(sueltos_de()), "ornizen",
                                miembro(5, "zoe", "colaborador"), miembro(4, "Beto", "editor"), miembro(3, "ana", "editor"),
                                miembro(2, "admin", "administrador"), miembro(1, "duena", "propietario"),
                                miembro(9, "nuevo", "editor", "invitado", invitadoPor=1))
        canal = canal_de(publicados(archivos, todo_el_modelo()), "ornizen")
        self.assertEqual([{"cuenta": "duena", "rol": "propietario"}, {"cuenta": "admin", "rol": "administrador"},
                          {"cuenta": "ana", "rol": "editor"}, {"cuenta": "Beto", "rol": "editor"},
                          {"cuenta": "zoe", "rol": "colaborador"}], canal["equipo"])
        self.assertEqual(5, canal["miembrosActivos"])

    def test_un_equipo_enorme_se_recorta(self):
        filas = [miembro(1, "duena", "propietario")] + [miembro(100 + i, f"u{i:03}") for i in range(450)]
        canal = canal_de(publicados(con_miembros(con_canales(sueltos_de()), "ornizen", *filas), todo_el_modelo()), "ornizen")
        self.assertEqual(publicar.MAX_EQUIPO_PUBLICADO, len(canal["equipo"]))
        self.assertEqual(451, canal["miembrosActivos"])
        self.assertEqual("duena", canal["equipo"][0]["cuenta"])

    def test_un_canal_bloqueado_no_ensena_equipo(self):
        archivos = con_miembros(con_canales(sueltos_de(), "rance_es"), "rance_es", miembro(7, "eva", "propietario"))
        archivos["canales/rance_es/canal.json"] = canal_json("rance_es", estado="bloqueado")
        canal = canal_de(publicados(archivos, todo_el_modelo()), "rance_es")
        self.assertEqual(([], 0), (canal["equipo"], canal["miembrosActivos"]))

    def test_nada_de_la_ficha_llega_a_main(self):
        archivos = con_ficha(con_miembros(con_canales(sueltos_de()), "ornizen", miembro(1, "duena", "propietario")),
                             "ornizen", ficha(destacado="rance-x"))
        for entrada in publicar.canales_para_main(archivos):
            self.assertFalse({"ficha", "equipo", "creado", "miembrosActivos"} & set(entrada), entrada)


if __name__ == "__main__":
    unittest.main()
