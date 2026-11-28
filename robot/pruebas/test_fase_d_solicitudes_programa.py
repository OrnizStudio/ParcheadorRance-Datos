"""Fase D, entrega 3b: las solicitudes de juego nuevo, edición nueva, ficha central y etiqueta global
(`robot/solicitudes.py`, integrado en `permisos.comprobar` y `permisos.solicitud_de`).

Un Administrador o un Propietario de un canal da de alta un juego o una edición (el canal, `alta.canal`) o cambia la
ficha central de un juego que su canal publica (el canal, la marca `<!-- canal: <c> -->` del cuerpo). Si el canal
está verificado en `main`, directo; si no, espera `aprobada`. La etiqueta es un archivo de solicitud que se fusiona.
"""

import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import particion  # noqa: E402
import solicitudes  # noqa: E402
from permisos import Cambio, Permisos, Rol, comprobar, solicitud_de  # noqa: E402
from test_fase_d_canales import OTRO, PARCHE_ES, canal_json, main_con_dos_canales  # noqa: E402
from test_fase_d_listas import canales_bloqueados, con, huellas  # noqa: E402
from test_sueltos import CATALOGO, HASH, HOY, HUELLA, YO, Propuesta  # noqa: E402

CANAL_ES = f"canales/{OTRO}/canal.json"
JUEGO_NUEVO = "juegos/rance-2/juego.json"
EDICION_NUEVA = "juegos/rance-2/ediciones/dl.json"
JUEGO = "juegos/rance/juego.json"
EDICION = "juegos/rance/ediciones/steam.json"
MARCA = f"<!-- canal: {OTRO} -->"


def admin(rol=Rol.ADMINISTRADOR, cuenta_id=YO):
    return Permisos(Rol.NINGUNO, por_canal={OTRO: rol}, cuenta_id=cuenta_id)


def main_es(verificado=False, estado="activo", **extra):
    main = main_con_dos_canales()
    objeto = canal_json(verificado=verificado)
    objeto["estado"] = estado
    main[CANAL_ES] = particion.texto_json(objeto)
    return con(main, **extra)


def alta(canal=OTRO, cuenta=YO):
    return {"canal": canal, "cuenta": cuenta, "fecha": HOY.isoformat()}


def con_juego_nuevo(main=None, canal=OTRO, deteccion=None, huella=None, alta_edicion=None):
    p = Propuesta(main if main is not None else main_es())
    juego = {"esquema": 1, "id": "rance-2", "titulo": "Rance 2", "estado": "activo", "alta": alta(canal),
             "ediciones": ["dl"]}
    if deteccion:
        juego["deteccion"] = deteccion
    p.poner(JUEGO_NUEVO, juego)
    p.poner(EDICION_NUEVA, {"esquema": 1, "id": "dl", "nombre": "DL", "huella": huella or HUELLA,
                            "alta": alta_edicion or alta(canal)})
    return p


def con_edicion_nueva(main=None, canal=OTRO):
    p = Propuesta(main if main is not None else main_es()).cambiar(JUEGO, lambda j: j["ediciones"].append("gog"))
    return p.poner("juegos/rance/ediciones/gog.json", {"esquema": 1, "id": "gog", "nombre": "GOG", "huella": HUELLA,
                                                        "alta": alta(canal)})


def juzgar(p, permisos=None, cuerpo="", abiertas=0, extra=(), etiquetas_main=None):
    texto = particion.texto_json(CATALOGO).decode("utf-8")
    lados = {"antes": p.antes, "despues": p.despues}
    pendientes = etiquetas_main if etiquetas_main is not None else {
        r: d for r, d in p.antes.items() if r.startswith(solicitudes.CARPETA_ETIQUETAS)}
    return comprobar(p.cambios(extra), texto, texto.encode(), permisos or admin(),
                     leer_archivo=lambda ruta, lado: lados[lado].get(ruta), leer_sueltos=lambda lado: lados[lado],
                     hoy=HOY, ids_duenos=frozenset({1}), solicitudes_abiertas=abiertas if callable(abiertas) else lambda etiqueta: abiertas,
                     cuerpo=cuerpo, listar_main=lambda carpeta: pendientes)


def sol(p, cuerpo=""):
    lados = {"antes": p.antes, "despues": p.despues}
    return solicitud_de(p.cambios(), lambda ruta, lado: lados[lado].get(ruta), lambda lado: lados[lado], cuerpo)


def hay(motivos, texto):
    return any(texto in m for m in motivos)


class JuegoNuevo(unittest.TestCase):
    def test_canal_sin_verificar_es_una_solicitud(self):
        p = con_juego_nuevo()
        self.assertEqual([], juzgar(p))
        s = sol(p)
        self.assertEqual(("juego", OTRO, "rance-2"), (s.tipo, s.canal, s.clave))
        self.assertTrue(s.necesita_aprobacion)
        self.assertEqual("solicitud:juego", s.etiqueta)

    def test_canal_verificado_va_directo(self):
        p = con_juego_nuevo(main_es(verificado=True))
        self.assertEqual([], juzgar(p))
        self.assertFalse(sol(p).necesita_aprobacion)
        # El tope de abiertas no cuenta para lo que va directo.
        self.assertEqual([], juzgar(p, abiertas=50))

    def test_el_propietario_tambien_y_el_editor_no(self):
        self.assertEqual([], juzgar(con_juego_nuevo(), admin(Rol.PROPIETARIO)))
        for rol in (Rol.NINGUNO, Rol.COLABORADOR, Rol.EDITOR):
            with self.subTest(rol=rol):
                self.assertTrue(hay(juzgar(con_juego_nuevo(), admin(rol)), "Administrador o un Propietario"))
        # Un Administrador de otro canal no da de alta en nombre de este.
        otro = Permisos(Rol.NINGUNO, por_canal={"ornizen": Rol.ADMINISTRADOR}, cuenta_id=YO)
        self.assertTrue(hay(juzgar(con_juego_nuevo(), otro), "Administrador o un Propietario"))

    def test_canal_que_no_existe_retirado_o_bloqueado(self):
        self.assertTrue(hay(juzgar(con_juego_nuevo(canal="nadie_aqui"), Permisos(
            Rol.NINGUNO, por_canal={"nadie_aqui": Rol.PROPIETARIO}, cuenta_id=YO)), "no existe"))
        self.assertTrue(hay(juzgar(con_juego_nuevo(main_es(estado="retirado"))), "no está activo"))
        bloqueado = con_juego_nuevo(main_es(verificado=True, lista=canales_bloqueados(OTRO)))
        self.assertTrue(hay(juzgar(bloqueado), "bloqueado"))

    def test_sin_alta_o_con_alta_ajena(self):
        p = con_juego_nuevo()
        p.cambiar(JUEGO_NUEVO, lambda j: j.pop("alta"))
        p.cambiar(EDICION_NUEVA, lambda e: e.pop("alta"))
        self.assertTrue(hay(juzgar(p), "`alta`"))
        p = con_juego_nuevo()
        p.cambiar(JUEGO_NUEVO, lambda j: j.update(alta=alta(cuenta=777)))
        self.assertTrue(hay(juzgar(p), "alta.cuenta"))

    def test_va_sola(self):
        con_parche = con_juego_nuevo().poner(f"canales/{OTRO}/parches/rance-2.json", {
            "esquema": 1, "juego": "rance-2", "habilitado": False, "orden": 2, "ediciones": [{"id": "dl"}]})
        self.assertTrue(hay(juzgar(con_parche), "Una solicitud va sola"))
        con_otro = con_juego_nuevo().cambiar(JUEGO, lambda j: j.update(titulo="Otro"))
        self.assertTrue(hay(juzgar(con_otro), "Una solicitud va sola"))
        con_normas = con_juego_nuevo().poner("normas/etiquetas.json", {"esquema": 1, "etiquetas": []})
        self.assertTrue(hay(juzgar(con_normas), "Una solicitud va sola"))
        self.assertIsNone(sol(con_parche))

    def test_altas_y_marca_que_no_cuadran(self):
        p = con_juego_nuevo(alta_edicion=alta("ornizen"))
        self.assertTrue(hay(juzgar(p), "`alta.canal` distintos"))
        self.assertTrue(hay(juzgar(con_juego_nuevo(), cuerpo="<!-- canal: ornizen -->"), "no coincide"))
        self.assertEqual([], juzgar(con_juego_nuevo(), cuerpo=f"Juego nuevo: Rance 2\n\n{MARCA}"))

    def test_mismo_id_de_steam_que_otro_juego(self):
        main = main_es()
        main[JUEGO] = particion.texto_json(dict(json.loads(main[JUEGO]), deteccion={"steamAppId": 123}))
        p = con_juego_nuevo(main, deteccion={"steamAppId": 123})
        self.assertTrue(hay(juzgar(p), "mismo id de Steam o de GOG"))
        self.assertEqual([], juzgar(con_juego_nuevo(main, deteccion={"steamAppId": 456})))

    def test_huella_vetada(self):
        malo = "blake3:" + "e" * 64
        huella = [{"ruta": "Rance.exe", "tamano": 10, "hashParcial": malo, "hash": malo}]
        p = con_juego_nuevo(main_es(lista=huellas(malo)), huella=huella)
        self.assertTrue(hay(juzgar(p), "Malware conocido"))

    def test_imagenes(self):
        p = con_juego_nuevo()
        bien = Cambio("catalogo/juegos/rance-2/portada.png", "A", tamano=1000)
        self.assertEqual([], juzgar(p, extra=[bien]))
        exe = Cambio("catalogo/juegos/rance-2/virus.exe", "A", tamano=10)
        self.assertTrue(hay(juzgar(p, extra=[exe]), "las imágenes de un juego van en"))
        enorme = Cambio("catalogo/juegos/rance-2/portada.png", "A", tamano=6 * 1024 * 1024)
        self.assertTrue(hay(juzgar(p, extra=[enorme]), "5 MB"))
        enlace = Cambio("catalogo/juegos/rance-2/portada.png", "A", modo="120000", tamano=10)
        self.assertTrue(hay(juzgar(p, extra=[enlace]), "archivos normales"))
        ajena = Cambio("catalogo/juegos/rance/portada.png", "A", tamano=10)
        self.assertTrue(hay(juzgar(p, extra=[ajena]), "Una solicitud va sola"))

    def test_tope_de_abiertas_por_cuenta(self):
        self.assertEqual([], juzgar(con_juego_nuevo(), abiertas=3))  # 3 por cada tipo: 9 en total
        self.assertTrue(hay(juzgar(con_juego_nuevo(), abiertas=4), f"{solicitudes.TOPE_ABIERTAS} solicitudes"))

    def test_varias_cuentas(self):
        self.assertTrue(hay(juzgar(con_juego_nuevo(), admin(cuenta_id=None)), "una sola cuenta"))

    def test_lo_que_la_app_no_lee_no_entra(self):
        p = con_juego_nuevo().cambiar(JUEGO_NUEVO, lambda j: j.update(titulo=["no", "es", "texto"]))
        self.assertTrue(juzgar(p))
        p = con_juego_nuevo().cambiar(JUEGO_NUEVO, lambda j: j.update(estado="bloqueado"))
        self.assertTrue(hay(juzgar(p), "empieza `activo`"))

    def test_el_dueno_sigue_directo_y_sin_solicitud(self):
        p = con_juego_nuevo().poner(f"canales/{OTRO}/parches/rance-2.json", {
            "esquema": 1, "juego": "rance-2", "habilitado": False, "orden": 2, "ediciones": [{"id": "dl"}]})
        self.assertEqual([], juzgar(p, Permisos(Rol.DUENO, cuenta_id=1)))

    def test_el_oficial_verificado_da_de_alta_directo(self):
        main = main_es()
        oficial = json.loads(main["canales/ornizen/canal.json"])
        oficial["verificacion"] = {"verificado": True}
        main["canales/ornizen/canal.json"] = particion.texto_json(oficial)
        p = con_juego_nuevo(main, canal="ornizen")
        equipo = Permisos(Rol.ADMINISTRADOR, por_canal={"ornizen": Rol.ADMINISTRADOR}, cuenta_id=YO)
        self.assertEqual([], juzgar(p, equipo))
        self.assertFalse(sol(p).necesita_aprobacion)
        editor = Permisos(Rol.EDITOR, por_canal={"ornizen": Rol.EDITOR}, cuenta_id=YO)
        self.assertTrue(hay(juzgar(p, editor), "Administrador o un Propietario"))


class EdicionNueva(unittest.TestCase):
    def test_solicitud_de_edicion(self):
        p = con_edicion_nueva()
        self.assertEqual([], juzgar(p))
        s = sol(p)
        self.assertEqual(("edicion", OTRO, "rance"), (s.tipo, s.canal, s.clave))
        self.assertTrue(s.necesita_aprobacion)
        self.assertFalse(sol(con_edicion_nueva(main_es(verificado=True))).necesita_aprobacion)

    def test_el_editor_no_y_el_juego_bloqueado_tampoco(self):
        self.assertTrue(hay(juzgar(con_edicion_nueva(), admin(Rol.EDITOR)), "Administrador o un Propietario"))
        main = main_es()
        main[JUEGO] = particion.texto_json(dict(json.loads(main[JUEGO]), estado="bloqueado"))
        self.assertTrue(hay(juzgar(con_edicion_nueva(main)), "bloqueado"))

    def test_sin_meterla_en_la_lista_del_juego(self):
        p = Propuesta(main_es()).poner("juegos/rance/ediciones/gog.json", {
            "esquema": 1, "id": "gog", "nombre": "GOG", "huella": HUELLA, "alta": alta()})
        self.assertTrue(juzgar(p))

    def test_la_del_oficial_sigue_como_siempre(self):
        # Una edición del oficial no es una solicitud: la registra un Editor del oficial, como en la fase B.
        p = con_edicion_nueva(canal="ornizen")
        self.assertIsNone(sol(p))
        self.assertEqual([], juzgar(p, Permisos(Rol.EDITOR, por_canal={"ornizen": Rol.EDITOR}, cuenta_id=YO)))


class FichaCentral(unittest.TestCase):
    def cambio(self, main=None):
        return Propuesta(main if main is not None else main_es()).cambiar(
            JUEGO, lambda j: j.update(titulo="Rance: Hikari wo Motomete"))

    def test_con_la_marca_y_parche_del_juego(self):
        p = self.cambio()
        self.assertEqual([], juzgar(p, cuerpo=f"Cambio en la ficha: Rance\n\n{MARCA}"))
        s = sol(p, MARCA)
        self.assertEqual(("central", OTRO, "rance"), (s.tipo, s.canal, s.clave))
        self.assertTrue(s.necesita_aprobacion)
        self.assertFalse(sol(self.cambio(main_es(verificado=True)), MARCA).necesita_aprobacion)

    def test_sin_parche_del_juego(self):
        main = main_es()
        del main[PARCHE_ES]
        self.assertTrue(hay(juzgar(self.cambio(main), cuerpo=MARCA), "no tiene parche"))

    def test_sin_marca_es_lo_de_siempre(self):
        # Sin la marca, se juzga con el rol del canal oficial: aquí ninguno.
        self.assertIsNone(sol(self.cambio()))
        self.assertTrue(juzgar(self.cambio()))

    def test_marcas_raras(self):
        for cuerpo, texto in ((f"{MARCA}\n<!-- canal: ornizen -->", "varias marcas"),
                              ("<!-- canal: ../../normas -->", "no lleva un @"),
                              ("<!-- canal: A -->", "no lleva un @")):
            with self.subTest(cuerpo=cuerpo):
                self.assertTrue(hay(juzgar(self.cambio(), cuerpo=cuerpo), texto))
        # La misma marca repetida vale; un cuerpo enorme no cuelga nada (solo se miran los primeros 64 KB).
        self.assertEqual([], juzgar(self.cambio(), cuerpo=f"{MARCA}\n{MARCA}"))
        self.assertEqual([], juzgar(self.cambio(), cuerpo=MARCA + "x" * 5_000_000))
        self.assertTrue(juzgar(self.cambio(), cuerpo="x" * 5_000_000 + MARCA))

    def test_la_huella_el_alta_y_el_estado_no(self):
        p = Propuesta(main_es()).cambiar(EDICION, lambda e: e.update(huella=[]))
        self.assertTrue(hay(juzgar(p, cuerpo=MARCA), "`huella`"))
        p = Propuesta(main_es()).cambiar(JUEGO, lambda j: j.update(estado="retirado"))
        self.assertTrue(hay(juzgar(p, cuerpo=MARCA), "`estado`"))
        p = Propuesta(main_es()).cambiar(JUEGO, lambda j: j.update(alta=alta()))
        self.assertTrue(hay(juzgar(p, cuerpo=MARCA), "`alta`"))

    def test_borrar_no(self):
        p = Propuesta(main_es()).quitar(EDICION).cambiar(JUEGO, lambda j: j.update(ediciones=[]))
        self.assertTrue(hay(juzgar(p, cuerpo=MARCA), "sin borrar nada"))

    def test_colaborador_del_canal_no(self):
        self.assertTrue(hay(juzgar(self.cambio(), admin(Rol.COLABORADOR), cuerpo=MARCA),
                            "Administrador o un Propietario"))


def cambio_central(main=None):
    return Propuesta(main if main is not None else main_es()).cambiar(JUEGO, lambda j: j.update(titulo="Rance: Hikari"))


class CasosExtremos(unittest.TestCase):
    """Lo que puede mandar alguien que no usa la app: vacío, enorme, repetido, en masa o de un juego que no existe."""

    def test_edicion_de_un_juego_que_no_existe(self):
        p = Propuesta(main_es()).poner("juegos/fantasma/ediciones/dl.json", {
            "esquema": 1, "id": "dl", "nombre": "DL", "huella": HUELLA, "alta": alta()})
        self.assertTrue(juzgar(p))
        self.assertTrue(juzgar(p, admin(Rol.PROPIETARIO)))

    def test_ficha_central_de_un_juego_que_no_existe(self):
        # Sin `juego.json` en main, «cambiarlo» es crearlo: un juego nuevo, con sus reglas (sin `alta`, no entra).
        p = Propuesta(main_es()).poner("juegos/fantasma/juego.json", {
            "esquema": 1, "id": "fantasma", "titulo": "F", "estado": "activo", "ediciones": []})
        self.assertTrue(juzgar(p, cuerpo=MARCA))

    def test_edicion_que_ya_existe(self):
        # Volver a «dar de alta» una edición que ya está no es una edición nueva: cambia su huella, y eso no.
        p = Propuesta(main_es()).cambiar(EDICION, lambda e: e.update(huella=[dict(HUELLA[0], tamano=11)], alta=alta()))
        self.assertTrue(juzgar(p, cuerpo=MARCA))
        self.assertNotEqual("edicion", getattr(sol(p, MARCA), "tipo", None))
        # La misma id dos veces en la lista del juego tampoco.
        p = con_edicion_nueva().cambiar(JUEGO, lambda j: j["ediciones"].append("gog"))
        self.assertTrue(juzgar(p))

    def test_vacios(self):
        for campo, valor in (("nombre", ""), ("nombre", "   "), ("huella", []), ("id", "")):
            with self.subTest(campo=campo, valor=valor):
                p = con_edicion_nueva().cambiar("juegos/rance/ediciones/gog.json", lambda e: e.update({campo: valor}))
                self.assertTrue(juzgar(p))
        p = Propuesta(main_es()).cambiar(JUEGO, lambda j: j.update(titulo=""))
        self.assertTrue(juzgar(p, cuerpo=MARCA))

    def test_textos_enormes_o_raros(self):
        for valor in ("G" * 10_000, "GOG‮", "G​OG", "GOG\nsegunda línea"):
            with self.subTest(valor=valor[:20]):
                p = con_edicion_nueva().cambiar("juegos/rance/ediciones/gog.json", lambda e: e.update(nombre=valor))
                self.assertTrue(juzgar(p))
                p = Propuesta(main_es()).cambiar(JUEGO, lambda j: j.update(tituloOriginal=valor))
                self.assertTrue(juzgar(p, cuerpo=MARCA))
        # Un id de edición enorme no llega ni a ser una edición del juego.
        largo = "g" * 300
        p = Propuesta(main_es()).cambiar(JUEGO, lambda j: j["ediciones"].append(largo))
        p.poner(f"juegos/rance/ediciones/{largo}.json", {"esquema": 1, "id": largo, "nombre": "G", "huella": HUELLA,
                                                         "alta": alta()})
        self.assertTrue(juzgar(p))

    def test_tope_repartido_entre_los_tres_tipos(self):
        def abiertas(cuantas):
            return lambda etiqueta: cuantas.get(etiqueta.removeprefix(solicitudes.PREFIJO_ETIQUETA), 0)
        self.assertEqual([], juzgar(con_edicion_nueva(), abiertas=abiertas({"juego": 9})))
        for cuantas in ({"juego": 10}, {"edicion": 10}, {"central": 10}, {"juego": 4, "edicion": 3, "central": 3}):
            with self.subTest(cuantas=cuantas):
                tope = f"{solicitudes.TOPE_ABIERTAS} solicitudes"
                self.assertTrue(hay(juzgar(con_edicion_nueva(), abiertas=abiertas(cuantas)), tope))
                self.assertTrue(hay(juzgar(cambio_central(), cuerpo=MARCA, abiertas=abiertas(cuantas)), tope))
        # Las de etiqueta no cuentan (tienen su propio tope, por canal); un canal verificado no tiene tope.
        self.assertEqual([], juzgar(con_edicion_nueva(), abiertas=abiertas({"etiqueta": 50})))
        self.assertEqual([], juzgar(con_edicion_nueva(main_es(verificado=True)), abiertas=lambda etiqueta: 99))

    def test_muchas_ediciones_de_golpe(self):
        p = Propuesta(main_es())
        ids = [f"e{n}" for n in range(60)]
        p.cambiar(JUEGO, lambda j: j["ediciones"].extend(ids))
        for e in ids:
            p.poner(f"juegos/rance/ediciones/{e}.json", {"esquema": 1, "id": e, "nombre": e, "huella": HUELLA,
                                                         "alta": alta()})
        self.assertTrue(juzgar(p))


ETIQUETA ="solicitudes/etiquetas/nandu-epico.json"


def etiqueta(**cambios):
    objeto = {"esquema": 1, "canal": OTRO, "nombre": "Ñandú Épico", "paraQue": "Juegos con avestruces.",
              "pedidaPor": YO, "fecha": HOY.isoformat()}
    objeto.update(cambios)
    return {k: v for k, v in objeto.items() if v is not None}


def con_etiqueta(main=None, ruta=ETIQUETA, **cambios):
    return Propuesta(main if main is not None else main_es()).poner(ruta, etiqueta(**cambios))


class Etiqueta(unittest.TestCase):
    def test_bien_se_fusiona(self):
        p = con_etiqueta()
        self.assertEqual([], juzgar(p))
        s = sol(p)
        self.assertEqual(("etiqueta", OTRO, "nandu-epico"), (s.tipo, s.canal, s.clave))
        self.assertFalse(s.necesita_aprobacion)

    def test_nombre_de_archivo(self):
        for nombre, esperado in (("Ñandú Épico", "nandu-epico"), ("  RPG  ", "rpg"), ("Straße", "strasse"),
                                 ("a--b__c", "a-b-c"), ("戦国", ""), ("x" * 40, "x" * 24),
                                 ("abcdefghijklmnopqrstuvw z", "abcdefghijklmnopqrstuvw"), (None, "")):
            with self.subTest(nombre=nombre):
                self.assertEqual(esperado, solicitudes.nombre_de_archivo(nombre))

    def test_archivo_que_no_es_el_del_nombre(self):
        self.assertTrue(hay(juzgar(con_etiqueta(ruta="solicitudes/etiquetas/otra.json")), "`nandu-epico.json`"))
        self.assertTrue(hay(juzgar(con_etiqueta(ruta="solicitudes/etiquetas/Ñandu.json")), "se llama como la"))
        self.assertTrue(hay(juzgar(con_etiqueta(ruta="solicitudes/etiquetas/x/nandu-epico.json")), "se llama como"))

    def test_campos(self):
        casos = ((dict(nombre="N" * 25), "`nombre`"), (dict(nombre="Hola\nmundo"), "`nombre`"),
                 (dict(nombre="‮RPG"), "`nombre`"), (dict(paraQue=""), "`paraQue`"),
                 (dict(paraQue="p" * 301), "`paraQue`"), (dict(paraQue=None), "`paraQue`"),
                 (dict(pedidaPor=1), "`pedidaPor`"), (dict(fecha="2026-01-01"), "`fecha`"),
                 (dict(estado="aceptada"), "los pone el Dueño"), (dict(respuesta="Sí"), "los pone el Dueño"),
                 (dict(esquema=2), "esquema"), (dict(color="rojo"), "solo valen"),
                 (dict(canal="no_existe"), "no existe"), (dict(canal="../normas"), "el @ de tu canal"),
                 (dict(canal=None), "el @ de tu canal"))
        for cambios, texto in casos:
            with self.subTest(cambios=cambios):
                ruta = ETIQUETA if "nombre" not in cambios else f"solicitudes/etiquetas/{solicitudes.nombre_de_archivo(cambios['nombre']) or 'x'}.json"
                self.assertTrue(hay(juzgar(con_etiqueta(ruta=ruta, **cambios)), texto), juzgar(con_etiqueta(ruta=ruta, **cambios)))
        self.assertTrue(hay(juzgar(con_etiqueta(ruta="solicitudes/etiquetas/x.json", nombre="戦国")), "una letra"))
        malo = Propuesta(main_es()).poner(ETIQUETA, b'{"esquema": 1, "canal": "rance_es", "canal": "x"}')
        self.assertTrue(juzgar(malo))
        enorme = Propuesta(main_es()).poner(ETIQUETA, b"[" * 100_000)
        self.assertTrue(juzgar(enorme))

    def test_solo_administrador_o_mas(self):
        for rol in (Rol.NINGUNO, Rol.COLABORADOR, Rol.EDITOR):
            with self.subTest(rol=rol):
                self.assertTrue(hay(juzgar(con_etiqueta(), admin(rol)), "Administrador o un Propietario"))
        self.assertEqual([], juzgar(con_etiqueta(), admin(Rol.PROPIETARIO)))
        self.assertTrue(hay(juzgar(con_etiqueta(), admin(cuenta_id=None)), "una sola cuenta"))

    def test_canal_retirado_o_bloqueado(self):
        self.assertTrue(hay(juzgar(con_etiqueta(main_es(estado="retirado"))), "no está activo"))
        self.assertTrue(hay(juzgar(con_etiqueta(main_es(lista=canales_bloqueados(OTRO)))), "bloqueado"))

    def test_ya_pedida_o_ya_existe(self):
        main = main_es()
        main[ETIQUETA] = particion.texto_json(etiqueta(estado="rechazada", respuesta="No", resuelta="2026-11-01"))
        p = Propuesta(main).cambiar(ETIQUETA, lambda e: e.update(paraQue="Otra vez"))
        self.assertTrue(hay(juzgar(p), "ya existe"))
        main = main_es()
        main["normas/etiquetas.json"] = particion.texto_json({"esquema": 1, "etiquetas": [
            {"id": "avestruz", "nombre": "Ñandú épico", "color": "rojo"}]})
        self.assertTrue(hay(juzgar(con_etiqueta(main)), "Ya existe la etiqueta «Ñandú épico»"))

    def test_diez_pendientes_por_canal(self):
        main = main_es()
        for i in range(solicitudes.TOPE_ABIERTAS):
            main[f"solicitudes/etiquetas/e{i}.json"] = particion.texto_json(etiqueta(nombre=f"E{i}"))
        self.assertTrue(hay(juzgar(con_etiqueta(main)), "10 solicitudes de etiqueta pendientes"))
        # Las resueltas y las de otros canales no cuentan.
        main["solicitudes/etiquetas/e0.json"] = particion.texto_json(etiqueta(nombre="E0", estado="aceptada"))
        main["solicitudes/etiquetas/e1.json"] = particion.texto_json(etiqueta(nombre="E1", canal="ornizen"))
        self.assertEqual([], juzgar(con_etiqueta(main)))
        demasiadas = {f"solicitudes/etiquetas/z{i}.json": b"" for i in range(solicitudes.TOPE_ARCHIVOS_ETIQUETA)}
        self.assertTrue(hay(juzgar(con_etiqueta(), etiquetas_main=demasiadas), "demasiadas"))

    def test_va_sola(self):
        p = con_etiqueta().poner("solicitudes/etiquetas/otra.json", etiqueta(nombre="Otra"))
        self.assertTrue(hay(juzgar(p), "Una solicitud va sola"))
        p = con_etiqueta().cambiar(JUEGO, lambda j: j.update(titulo="X"))
        self.assertTrue(hay(juzgar(p), "Una solicitud va sola"))
        main = main_es()
        main[ETIQUETA] = particion.texto_json(etiqueta())
        self.assertTrue(hay(juzgar(Propuesta(main).quitar(ETIQUETA)), "Una solicitud va sola"))


class ListarDeMain(unittest.TestCase):
    def test_archivos_de_carpeta_con_git(self):
        """Lo que lee `main()` de `solicitudes/etiquetas/`: solo `.json` normales de esa carpeta, con topes."""
        import os
        import subprocess
        import tempfile
        import permisos
        with tempfile.TemporaryDirectory() as carpeta:
            def g(*a, entrada=None):
                return subprocess.run(["git", "-C", carpeta, *a], capture_output=True, check=True, input=entrada)
            g("init", "-q")
            g("config", "user.email", "robot@example.invalid")
            g("config", "user.name", "robot")
            raiz = pathlib.Path(carpeta, "solicitudes", "etiquetas")
            (raiz / "sub").mkdir(parents=True)
            (raiz / "a.json").write_bytes(b'{"canal": "x"}')
            (raiz / "b.json").write_bytes(b"x" * 100)
            (raiz / "notas.txt").write_bytes(b"no")
            (raiz / "sub" / "c.json").write_bytes(b"{}")
            g("add", ".")
            enlace = g("hash-object", "-w", "--stdin", entrada=b"../../normas/propietario.json").stdout.decode().strip()
            g("update-index", "--add", "--cacheinfo", f"120000,{enlace},solicitudes/etiquetas/enlace.json")
            g("commit", "-qm", "uno")
            actual = os.getcwd()
            os.chdir(carpeta)
            try:
                leidos = permisos.archivos_de_carpeta("HEAD", "solicitudes/etiquetas/", 50, 10)
                self.assertEqual({"solicitudes/etiquetas/a.json": b'{"canal": "x"}',
                                  "solicitudes/etiquetas/b.json": b""}, leidos)
                # Pasado el tope se corta (uno más, sin leer: quien llama sabe que hay demasiados).
                self.assertEqual(2, len(permisos.archivos_de_carpeta("HEAD", "solicitudes/etiquetas/", 50, 1)))
                self.assertEqual({}, permisos.archivos_de_carpeta("HEAD", "no/existe/", 50, 10))
            finally:
                os.chdir(actual)


if __name__ == "__main__":
    unittest.main()
