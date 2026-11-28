"""Cambiar el @ de un canal (`robot/cambio_arroba.py`, docs/canales.md §7.1): la propuesta mueve la carpeta entera."""

import datetime
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import cambio_arroba  # noqa: E402
import particion  # noqa: E402
from permisos import Cambio, Permisos, Rol, comprobar  # noqa: E402
from test_fase_d_canales import OTRO, PARCHE_ES, canal_json, main_con_dos_canales  # noqa: E402
from test_fase_d_listas import canales_bloqueados  # noqa: E402
from test_sueltos import CATALOGO, HOY, YO, Propuesta  # noqa: E402

NUEVO = "rance_ib"
LOGO = "logo.png"


def miembros(*filas):
    return {"esquema": 1, "miembros": list(filas) or [
        {"id": YO, "cuenta": "yo", "rol": "propietario", "desde": "2026-11-21", "estado": "activo"}]}


def main_base(anteriores=None, **campos):
    archivos = main_con_dos_canales()
    canal = canal_json()
    canal["logo"] = LOGO
    if anteriores is not None:
        canal["idAnteriores"] = anteriores
    canal.update(campos)
    archivos[f"canales/{OTRO}/canal.json"] = particion.texto_json(canal)
    archivos[f"canales/{OTRO}/miembros.json"] = particion.texto_json(miembros())
    archivos[f"canales/{OTRO}/ficha.json"] = particion.texto_json({"esquema": 1, "descripcion": "Hola"})
    archivos[f"canales/{OTRO}/{LOGO}"] = b"\x89PNG\r\n\x1a\nlogo"
    return archivos


def mover(main=None, viejo=OTRO, nuevo=NUEVO, fila=None, en_canal=None):
    """La propuesta que hace la app: borra la carpeta vieja y la pone entera en la nueva."""
    p = Propuesta(main if main is not None else main_base())
    for ruta in [r for r in p.antes if r.startswith(f"canales/{viejo}/")]:
        datos = p.despues.pop(ruta)
        resto = ruta[len(f"canales/{viejo}/"):]
        if resto == "canal.json":
            canal = json.loads(datos)
            canal["id"] = nuevo
            canal["idAnteriores"] = list(canal.get("idAnteriores", [])) + [
                fila if fila is not None else {"id": viejo, "desde": "2026-11-21", "hasta": HOY.isoformat()}]
            if en_canal:
                en_canal(canal)
            datos = particion.texto_json(canal)
        p.despues[f"canales/{nuevo}/{resto}"] = datos
    return p


def juzgar(p, permisos=None, etiquetas=None, ahora=None, canales_main=None):
    """`canales_main`: el `catalogo/canales.json` de `main` (objeto), con las horas de los cambios de @."""
    texto = particion.texto_json(CATALOGO).decode("utf-8")
    lados = {"antes": dict(p.antes), "despues": p.despues}
    if canales_main is not None:
        lados["antes"]["catalogo/canales.json"] = particion.texto_json(canales_main)
    return comprobar(p.cambios(), texto, texto.encode(),
                     permisos or Permisos(Rol.NINGUNO, por_canal={OTRO: Rol.PROPIETARIO}, cuenta_id=YO),
                     leer_archivo=lambda ruta, lado: lados[lado].get(ruta), leer_sueltos=lambda lado: lados[lado],
                     hoy=HOY, ahora=ahora, listar_main=lambda carpeta: {r: d for r, d in (etiquetas or {}).items()
                                                                        if r.startswith(carpeta)})


def utc(texto):
    return datetime.datetime.fromisoformat(texto).replace(tzinfo=datetime.timezone.utc)


def con_hora(canal, arroba, hasta, cambio):
    """Un `catalogo/canales.json` de `main` con la hora del cambio de `canal` de `arroba` apuntada."""
    return {"esquema": 1, "canales": [{"id": canal, "redirige": [{"id": arroba, "hasta": hasta, "cambio": cambio}]}]}


DUENO = Permisos(Rol.DUENO, cuenta_id=1)
ADMIN = Permisos(Rol.NINGUNO, por_canal={OTRO: Rol.ADMINISTRADOR}, cuenta_id=YO)


def hay(motivos, texto):
    return any(texto in m for m in motivos)


class Detectar(unittest.TestCase):
    def test_solo_una_carpeta_que_se_va_y_otra_que_llega_con_su_canal_json(self):
        self.assertEqual((OTRO, NUEVO), cambio_arroba.detectar(mover().cambios()))
        # Algo fuera de `canales/`, tres carpetas o una carpeta tocada a medias: no es un cambio de @.
        self.assertIsNone(cambio_arroba.detectar(mover().cambios([Cambio("juegos/x/juego.json", "M")])))
        self.assertIsNone(cambio_arroba.detectar(mover().cambios([Cambio("canales/otro/canal.json", "A")])))
        self.assertIsNone(cambio_arroba.detectar([Cambio(f"canales/{OTRO}/canal.json", "M")]))
        self.assertIsNone(cambio_arroba.detectar([Cambio(f"canales/{OTRO}/miembros.json", "D"),
                                                  Cambio(f"canales/{NUEVO}/miembros.json", "A")]))
        self.assertIsNone(cambio_arroba.detectar([]))


class CambioDeArroba(unittest.TestCase):
    def test_bien_hecho_lo_acepta_el_robot(self):
        self.assertEqual([], juzgar(mover()))
        # Sin `desde` también vale; y el Dueño puede.
        self.assertEqual([], juzgar(mover(fila={"id": OTRO, "hasta": HOY.isoformat()})))
        self.assertEqual([], juzgar(mover(), DUENO))

    def test_solo_el_propietario_o_el_dueno(self):
        self.assertTrue(hay(juzgar(mover(), ADMIN), "solo lo cambia su Propietario"))
        self.assertTrue(hay(juzgar(mover(), Permisos(Rol.ADMINISTRADOR, cuenta_id=YO)), "solo lo cambia su Propietario"))
        self.assertTrue(hay(juzgar(mover(), Permisos(Rol.NINGUNO, por_canal={OTRO: Rol.PROPIETARIO})), "una sola cuenta"))

    def test_una_vez_cada_30_dias(self):
        def con_ultimo(dias):
            hasta = (HOY - datetime.timedelta(days=dias)).isoformat()
            return mover(main_base([{"id": "rance_viejo", "hasta": hasta}]),
                         fila={"id": OTRO, "desde": hasta, "hasta": HOY.isoformat()})
        motivos = juzgar(con_ultimo(29))
        self.assertTrue(hay(motivos, "una vez cada 30 días"), motivos)
        self.assertTrue(hay(motivos, f"desde el {(HOY + datetime.timedelta(days=1)).isoformat()}"), motivos)
        self.assertTrue(hay(juzgar(con_ultimo(0)), "una vez cada 30 días"))
        self.assertEqual([], juzgar(con_ultimo(30)))
        self.assertEqual([], juzgar(con_ultimo(29), DUENO))  # el Dueño lo arregla si hace falta
        # Una fecha de `idAnteriores` del futuro también cuenta como reciente.
        self.assertTrue(hay(juzgar(con_ultimo(-400)), "una vez cada 30 días"))

    def test_el_arroba_de_otro_canal_no(self):
        # Encima de una carpeta que existe: ni siquiera tiene forma de cambio de @ (su canal.json cambia), y no pasa.
        self.assertIsNone(cambio_arroba.detectar(mover(nuevo="ornizen").cambios()))
        self.assertTrue(juzgar(mover(nuevo="ornizen")))
        # Dos canales que piden a la vez el mismo @ libre: el primero que se fusiona crea la carpeta; el segundo choca
        # con ella (ya no es un cambio de @) y no pasa.
        main = main_base()
        main["canales/libre_ya/canal.json"] = particion.texto_json(canal_json("libre_ya", nombre="Libre"))
        self.assertTrue(juzgar(mover(main, nuevo="libre_ya")))

    def test_uno_que_ha_dejado_otro_canal_queda_bloqueado_24_horas(self):
        main = main_base()
        main["canales/ornizen/canal.json"] = particion.texto_json(
            {**json.loads(main["canales/ornizen/canal.json"]),
             "idAnteriores": [{"id": "orn_viejo", "hasta": HOY.isoformat()}]})
        hora = con_hora("ornizen", "orn_viejo", HOY.isoformat(), "2026-11-24T10:00:00Z")
        # Justo antes de las 24 h, bloqueado (con el día y la hora en que queda libre); a las 24 h en punto, libre.
        motivos = juzgar(mover(main, nuevo="orn_viejo"), ahora=utc("2026-11-25T09:59:59"), canales_main=hora)
        self.assertTrue(hay(motivos, "bloqueado 24 horas"), motivos)
        self.assertTrue(hay(motivos, "2026-11-25 a las 10:00:00 (UTC)"), motivos)
        self.assertEqual([], juzgar(mover(main, nuevo="orn_viejo"), ahora=utc("2026-11-25T10:00:00"),
                                    canales_main=hora))
        # Su parecido también: mientras está bloqueado, «orn_vlejo» se confunde con él; después, no.
        self.assertTrue(juzgar(mover(main, nuevo="orn_vlejo"), ahora=utc("2026-11-24T11:00:00"), canales_main=hora))
        self.assertEqual([], juzgar(mover(main, nuevo="orn_vlejo"), ahora=utc("2026-11-26T00:00:00"),
                                    canales_main=hora))
        # Sin la hora (el robot aún no la ha apuntado: se acaba de fusionar), bloqueado hasta el final del día
        # siguiente a `hasta`; con una hora que no se puede leer, igual.
        for sin_hora in (None, con_hora("ornizen", "orn_viejo", HOY.isoformat(), "ayer"),
                         con_hora("ornizen", "orn_viejo", "2026-11-23", "2026-11-24T10:00:00Z"),
                         {"canales": "no es una lista"}, ["raro"]):
            with self.subTest(sin_hora=sin_hora):
                self.assertTrue(hay(juzgar(mover(main, nuevo="orn_viejo"), ahora=utc("2026-11-25T23:59:59"),
                                           canales_main=sin_hora), "bloqueado"))
                self.assertEqual([], juzgar(mover(main, nuevo="orn_viejo"), ahora=utc("2026-11-26T00:00:00"),
                                            canales_main=sin_hora))
        # Una hora del futuro (un reloj adelantado): cuenta desde ella, así que sigue bloqueado.
        futuro = con_hora("ornizen", "orn_viejo", HOY.isoformat(), "2027-01-01T00:00:00Z")
        self.assertTrue(hay(juzgar(mover(main, nuevo="orn_viejo"), ahora=utc("2026-11-30T00:00:00"),
                                   canales_main=futuro), "bloqueado"))
        # Uno dejado hace mucho: libre para cualquiera.
        main["canales/ornizen/canal.json"] = particion.texto_json(
            {**json.loads(main["canales/ornizen/canal.json"]),
             "idAnteriores": [{"id": "orn_viejo", "hasta": "2026-01-01"}]})
        self.assertEqual([], juzgar(mover(main, nuevo="orn_viejo")))

    def test_volver_a_su_arroba_de_antes(self):
        # A→B→A: el Propietario no puede antes de 30 días (su límite); pasados, sí: las 24 h ya han pasado.
        def volver(dias, permisos=None, ahora=None):
            hasta = (HOY - datetime.timedelta(days=dias)).isoformat()
            return juzgar(mover(main_base([{"id": "rance_viejo", "hasta": hasta}]), nuevo="rance_viejo",
                                fila={"id": OTRO, "hasta": HOY.isoformat()}), permisos, ahora=ahora)
        self.assertTrue(hay(volver(5), "una vez cada 30 días"))
        self.assertEqual([], volver(30))
        # El Dueño no tiene el límite, pero sí las 24 h, como todos.
        self.assertTrue(hay(volver(0, DUENO), "bloqueado 24 horas"))
        self.assertTrue(hay(volver(1, DUENO, utc("2026-11-24T23:59:59")), "bloqueado"))
        self.assertEqual([], volver(2, DUENO))

    def test_reservado_confundible_o_que_no_vale(self):
        self.assertTrue(hay(juzgar(mover(nuevo="programa")), "reservado por el programa"))
        self.assertTrue(juzgar(mover(nuevo="orniz_fans")))  # «orniz…» es del Dueño
        self.assertTrue(hay(juzgar(mover(nuevo="0rnizen")), "@0rnizen"))
        for malo in ("Rance-IB", "ab", "a" * 21, "rance ib", "ránce", "x" * 10_000, "../fuera"):
            with self.subTest(malo=malo[:30]):
                self.assertTrue(juzgar(mover(nuevo=malo)))
        # Parecido a sí mismo no cuenta: su @ de ahora y su nombre no se comparan con el nuevo.
        self.assertEqual([], juzgar(mover(nuevo="rance_e5")))

    def test_el_oficial_un_bloqueado_o_uno_retirado_no(self):
        self.assertTrue(hay(juzgar(mover(viejo="ornizen", nuevo="ornizen2"), DUENO), "canal oficial"))
        bloqueado = main_base()
        bloqueado.update(canales_bloqueados(OTRO))
        self.assertTrue(hay(juzgar(mover(bloqueado)), "bloqueado"))
        self.assertTrue(hay(juzgar(mover(main_base(estado="retirado"))), "no está activo"))

    def test_la_carpeta_se_mueve_entera_y_sin_cambiar(self):
        # Un archivo que se queda en la vieja.
        p = mover()
        p.despues[f"canales/{OTRO}/miembros.json"] = p.antes[f"canales/{OTRO}/miembros.json"]
        del p.despues[f"canales/{NUEVO}/miembros.json"]
        self.assertTrue(juzgar(p))
        # Un parche que se queda (se borra sin llegar a la nueva).
        p = mover()
        del p.despues[PARCHE_ES.replace(OTRO, NUEVO)]
        self.assertTrue(hay(juzgar(p), "la carpeta se mueve entera"))
        # Un byte cambiado, en el logo o en los miembros.
        for resto in (LOGO, "miembros.json", "ficha.json", "parches/rance.json"):
            with self.subTest(resto=resto):
                p = mover()
                p.despues[f"canales/{NUEVO}/{resto}"] += b" "
                self.assertTrue(hay(juzgar(p), "no es igual que"))
        # Un archivo de más en la nueva.
        p = mover()
        p.despues[f"canales/{NUEVO}/parches/otro.json"] = b"{}"
        self.assertTrue(hay(juzgar(p), "no se añade nada"))

    def test_en_canal_json_solo_cambian_id_e_id_anteriores(self):
        self.assertTrue(hay(juzgar(mover(en_canal=lambda c: c.update(nombre="Otro nombre"))), "solo cambian `id`"))
        self.assertTrue(juzgar(mover(en_canal=lambda c: c.update(verificacion={"verificado": True}))))
        self.assertTrue(juzgar(mover(en_canal=lambda c: c.update(id="otro_id"))))
        self.assertTrue(juzgar(mover(en_canal=lambda c: c.update(campoRaro=1))))

    def test_la_fila_de_id_anteriores(self):
        malas = [
            {"id": "otro", "hasta": HOY.isoformat()},
            {"id": OTRO, "hasta": "2026-01-01"},
            {"id": OTRO, "hasta": "no es fecha"},
            {"id": OTRO},
            {"id": OTRO, "desde": "2027-01-01", "hasta": HOY.isoformat()},
            {"id": OTRO, "hasta": HOY.isoformat(), "extra": 1},
        ]
        for fila in malas:
            with self.subTest(fila=fila):
                self.assertTrue(juzgar(mover(fila=fila)))
        # Sin fila nueva, con las de antes cambiadas o quitadas.
        main = main_base([{"id": "rance_viejo", "hasta": "2026-01-01"}])
        self.assertTrue(juzgar(mover(main, en_canal=lambda c: c.update(idAnteriores=c["idAnteriores"][-1:]))))
        self.assertTrue(juzgar(mover(en_canal=lambda c: c.pop("idAnteriores"))))
        # Muchísimas: no caben en los 16 KB de `canal.json` (y el robot tiene además su tope de filas).
        muchas = [{"id": f"c{i:05}", "hasta": "2000-01-01"} for i in range(cambio_arroba.TOPE_ANTERIORES)]
        self.assertTrue(hay(juzgar(mover(main_base(muchas))), "el máximo son"))

    def test_con_una_solicitud_sin_resolver_no(self):
        main = main_base()
        main[f"solicitudes/verificacion/{OTRO}.json"] = particion.texto_json({"esquema": 1, "canal": OTRO})
        self.assertTrue(hay(juzgar(mover(main)), "la verificación"))
        main[f"solicitudes/verificacion/{OTRO}.json"] = particion.texto_json(
            {"esquema": 1, "canal": OTRO, "estado": "aceptada", "respuesta": "Sí", "resuelta": "2026-11-01"})
        self.assertEqual([], juzgar(mover(main)))
        etiqueta = {"solicitudes/etiquetas/beta.json": particion.texto_json({"esquema": 1, "canal": OTRO, "nombre": "Beta"})}
        self.assertTrue(hay(juzgar(mover(), etiquetas=etiqueta), "la etiqueta"))
        otra = {"solicitudes/etiquetas/beta.json": particion.texto_json({"esquema": 1, "canal": "ornizen", "nombre": "B"})}
        self.assertEqual([], juzgar(mover(), etiquetas=otra))

    def test_dos_carpetas_nuevas_o_una_movida_y_otra_tocada_no_pasan(self):
        p = mover()
        p.despues["canales/ornizen/ficha.json"] = b"{}"
        self.assertTrue(juzgar(p))



class Redirige(unittest.TestCase):
    """`catalogo/canales.json` lleva los últimos @ con su `hasta`, para que la app redirija 90 días."""

    def entrada(self, anteriores):
        import publicar
        archivos = main_base(anteriores)
        return next(c for c in publicar.canales_para_main(archivos) if c["id"] == OTRO)

    def test_los_ultimos_con_su_fecha_del_mas_reciente_al_mas_antiguo(self):
        filas = [{"id": f"rance_{i}", "hasta": f"2026-0{i}-01"} for i in range(1, 7)]
        entrada = self.entrada(filas)
        self.assertEqual([f"rance_{i}" for i in range(1, 7)], entrada["idAnteriores"])
        self.assertEqual([{"id": f"rance_{i}", "hasta": f"2026-0{i}-01"} for i in (6, 5, 4, 3)], entrada["redirige"])

    def test_lo_que_no_vale_no_redirige(self):
        filas = [{"id": "rance_ok", "hasta": "2026-11-01"}, {"id": "Mal", "hasta": "2026-11-02"},
                 {"id": "sin_fecha"}, {"id": "fecha_mala", "hasta": "ayer"}, {"id": OTRO, "hasta": "2026-11-03"},
                 {"id": "rance_ok", "hasta": "2026-11-04"}, "no es un objeto"]
        self.assertEqual([{"id": "rance_ok", "hasta": "2026-11-04"}], self.entrada(filas)["redirige"])
        self.assertNotIn("redirige", self.entrada(None))
        self.assertNotIn("redirige", self.entrada([{"id": "sin_fecha"}]))

    def test_la_hora_del_cambio_se_apunta_una_vez_y_se_guarda(self):
        import publicar
        archivos = main_base([{"id": "rance_a", "hasta": "2026-11-01"}, {"id": "rance_b", "hasta": "2026-11-24"}])
        avisos = []
        primera = json.loads(publicar.regenerados(archivos, None, None, avisos, ahora=utc("2026-11-24T10:00:00"))
                             [publicar.RUTA_CANALES_MAIN])
        entrada = next(c for c in primera["canales"] if c["id"] == OTRO)
        self.assertEqual([{"id": "rance_b", "hasta": "2026-11-24", "cambio": "2026-11-24T10:00:00Z"},
                          {"id": "rance_a", "hasta": "2026-11-01", "cambio": "2026-11-24T10:00:00Z"}],
                         entrada["redirige"])
        # La siguiente vez, la hora es la de antes, no la nueva.
        segunda = publicar.regenerados(archivos, None, particion.texto_json(primera), avisos,
                                       ahora=utc("2026-11-30T00:00:00"))
        self.assertNotIn(publicar.RUTA_CANALES_MAIN, segunda)  # nada ha cambiado: no se reescribe
        # Sin `ahora` (llamadas antiguas), sin hora.
        self.assertNotIn("cambio", publicar.canales_para_main(archivos)[0].get("redirige", [{}])[0])

    def test_si_otro_canal_toma_el_arroba_deja_de_redirigir(self):
        import publicar
        archivos = main_base([{"id": "rance_a", "hasta": "2026-11-01"}, {"id": "rance_b", "hasta": "2026-11-24"}])
        archivos["canales/rance_b/canal.json"] = particion.texto_json(canal_json("rance_b", nombre="Otro canal"))
        entrada = next(c for c in publicar.canales_para_main(archivos) if c["id"] == OTRO)
        self.assertEqual(["rance_a"], [r["id"] for r in entrada["redirige"]])
        self.assertIn("rance_b", entrada["idAnteriores"])  # la historia sigue entera


if __name__ == "__main__":
    unittest.main()
