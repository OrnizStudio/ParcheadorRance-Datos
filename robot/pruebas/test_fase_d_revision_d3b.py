"""Revisión de D3b (#52): una «edición nueva» que de paso cambia la ficha es un cambio de ficha central, los ids de
tienda escritos de otra forma son el mismo id (también al cambiar la `deteccion`) y, con D4b, nadie pide un canal con
los repositorios de otro."""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import particion  # noqa: E402
import permisos  # noqa: E402
import test_fase_d_solicitudes as S  # noqa: E402
from test_fase_d_solicitudes_programa import (EDICION, JUEGO, MARCA, PARCHE_ES, Propuesta, con_edicion_nueva,  # noqa: E402
                                              con_juego_nuevo, hay, juzgar, main_es, sol)


def con_deteccion(main, deteccion):
    main = dict(main)
    main[JUEGO] = particion.texto_json(dict(json.loads(main[JUEGO]), deteccion=deteccion))
    return main


class EdicionQueTocaLaFicha(unittest.TestCase):
    def sin_parche(self, verificado=True):
        main = main_es(verificado=verificado)
        del main[PARCHE_ES]
        return main

    def test_solo_la_edicion_sigue_siendo_edicion(self):
        p = con_edicion_nueva(self.sin_parche())
        self.assertEqual("edicion", sol(p).tipo)
        self.assertEqual([], juzgar(p))

    def test_con_la_ficha_cambiada_es_ficha_central_y_pide_parche(self):
        for cambio in (lambda j: j.update(titulo="TITULO CAMBIADO"),
                       lambda j: j.update(deteccion={"steamAppId": 999, "ejecutables": ["malo.exe"]}),
                       lambda j: j.update(ediciones=["gog", *j["ediciones"]]),   # la nueva, delante
                       lambda j: j["ediciones"].append("otra"),                   # un id que no es el de la edición
                       lambda j: j.update(ediciones=j["ediciones"][1:])):          # quita una que estaba
            with self.subTest():
                p = con_edicion_nueva(self.sin_parche()).cambiar(JUEGO, cambio)
                self.assertEqual("central", sol(p).tipo)
                self.assertTrue(hay(juzgar(p), "no tiene parche"))

    def test_tocar_una_edicion_que_ya_esta_tambien(self):
        p = con_edicion_nueva(self.sin_parche()).cambiar(EDICION, lambda e: e.update(nombre="Steam (cambiada)"))
        self.assertEqual("central", sol(p).tipo)
        self.assertTrue(hay(juzgar(p), "no tiene parche"))

    def test_una_imagen_tambien(self):
        p = con_edicion_nueva(self.sin_parche())
        p.despues["catalogo/juegos/rance/portada.png"] = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        self.assertEqual("central", sol(p).tipo)

    def test_con_parche_del_juego_el_cambio_en_la_ficha_vale_como_central(self):
        p = con_edicion_nueva(main_es(verificado=True)).cambiar(JUEGO, lambda j: j.update(titulo="Rance (nuevo)"))
        self.assertEqual("central", sol(p).tipo)
        self.assertEqual([], juzgar(p))


class IdsDeTienda(unittest.TestCase):
    def test_variantes_del_mismo_numero(self):
        for viejo, nuevo in (({"gogId": 123}, {"gogId": "0123"}), ({"gogId": 123}, {"gogId": "+123"}),
                             ({"gogId": "123"}, {"gogId": 123}), ({"steamAppId": 123}, {"steamAppId": 123.0}),
                             ({"steamAppId": 123}, {"steamAppId": " 123 "}), ({"gogId": "ABC"}, {"gogId": "abc"})):
            with self.subTest(viejo=viejo, nuevo=nuevo):
                p = con_juego_nuevo(con_deteccion(main_es(), viejo), deteccion=nuevo)
                self.assertTrue(hay(juzgar(p), "mismo id de Steam o de GOG"))

    def test_lo_que_no_es_el_mismo(self):
        self.assertEqual(set(), permisos._ids_de_tienda({"deteccion": {"steamAppId": 0, "gogId": "  "}}))
        self.assertEqual(set(), permisos._ids_de_tienda({"deteccion": {"steamAppId": True, "gogId": 1.5}}))
        self.assertEqual({("gogId", "123")}, permisos._ids_de_tienda({"deteccion": {"gogId": "0123"}}))
        # Steam 123 y GOG 123 son de tiendas distintas.
        self.assertEqual([], juzgar(con_juego_nuevo(con_deteccion(main_es(), {"steamAppId": 123}),
                                                    deteccion={"gogId": 123})))
        # Entradas raras: ni fallan ni cuentan.
        for raro in (None, [], "x", {"deteccion": "x"}, {"deteccion": {"gogId": [1]}}):
            self.assertEqual(set(), permisos._ids_de_tienda(raro))

    def test_tambien_al_cambiar_la_deteccion_en_la_ficha_central(self):
        main = main_es()
        main["juegos/otro/juego.json"] = particion.texto_json(
            {"esquema": 1, "id": "otro", "titulo": "Otro", "estado": "activo", "ediciones": [],
             "deteccion": {"steamAppId": 777}})
        p = Propuesta(main).cambiar(JUEGO, lambda j: j.update(deteccion={"steamAppId": "0777"}))
        self.assertTrue(hay(juzgar(p, cuerpo=MARCA), "mismo id de Steam o de GOG"))
        # Lo que ya tenía no cuenta: un cambio de título con un id que ya chocaba antes no se frena por eso.
        main = con_deteccion(main, {"steamAppId": 777})
        p = Propuesta(main).cambiar(JUEGO, lambda j: j.update(titulo="Rance (bien)"))
        self.assertFalse(hay(juzgar(p, cuerpo=MARCA), "mismo id de Steam o de GOG"))

    def test_y_en_una_edicion_nueva_que_toca_la_deteccion(self):
        main = main_es()
        main["juegos/otro/juego.json"] = particion.texto_json(
            {"esquema": 1, "id": "otro", "titulo": "Otro", "estado": "activo", "ediciones": [],
             "deteccion": {"gogId": 55}})
        p = con_edicion_nueva(main).cambiar(JUEGO, lambda j: j.update(deteccion={"gogId": "+55"}))
        self.assertTrue(hay(juzgar(p), "mismo id de Steam o de GOG"))


class CanalNuevoConRepositoriosAjenos(unittest.TestCase):
    def test_de_OrnizStudio_o_de_otro_canal_no(self):
        main = S.main_con_dos_canales()
        objeto = json.loads(main[f"canales/{S.OTRO}/canal.json"])
        objeto["paquetes"] = ["rance-es/parches"]
        main[f"canales/{S.OTRO}/canal.json"] = particion.texto_json(objeto)
        for paquetes, texto in ((["OrnizStudio/Ornizen-Parches"], "OrnizStudio"),
                                (["Rance-ES/Parches"], f"@{S.OTRO}")):
            with self.subTest(paquetes=paquetes):
                self.assertTrue(S.hay(S.juzgar(S.nuevo_canal(main, paquetes=paquetes)), texto))
        self.assertEqual([], S.juzgar(S.nuevo_canal(main, paquetes=["galos/parches"])))


if __name__ == "__main__":
    unittest.main()
