"""Pruebas de los topes de largo de los textos del catálogo.  Uso:  python -m unittest discover -s robot/pruebas"""
import copy
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from permisos import (Cambio, Permisos, Rol, RUTA_CATALOGO, comprobar, comprobar_largos,  # noqa: E402
                      LARGO_NOTA_EDICION, LARGO_NOVEDADES, LARGO_SINOPSIS, LARGO_VERSION)

HASH = "blake3:" + "a" * 64
PROPIETARIO, EDITOR, COLABORADOR = Permisos(Rol.DUENO), Permisos(Rol.EDITOR), Permisos(Rol.COLABORADOR)
BASE = {
    "esquema": 1, "versionCatalogo": 5, "etiquetas": [],
    "juegos": [{
        "id": "juego1", "titulo": "Juego 1", "sinopsis": "Antes",
        "parche": {"version": "1.0.0", "notas": "Primera"},
        "ediciones": [{
            "id": "steam", "nombre": "Steam", "notaEdicion": "", "huella": [],
            "parche": {"version": "1.0.0", "notas": "Primera"},
            "versiones": [{"version": "1.0.0", "estado": "publico", "notas": "Primera"}],
            "huellasParcheadas": [{"version": "1.0.0", "archivos": []}],
        }],
    }],
}


def cambiado(cambiar, base=BASE):
    despues = copy.deepcopy(base)
    despues["versionCatalogo"] += 1
    cambiar(despues["juegos"][0], despues["juegos"][0]["ediciones"][0])
    return despues


def motivos(cambiar, base=BASE):
    return comprobar_largos(base, cambiado(cambiar, base))


class Topes(unittest.TestCase):
    def test_justo_en_el_tope_vale_y_uno_mas_no(self):
        casos = [
            (lambda j, e, n: j.update(sinopsis="a" * n), LARGO_SINOPSIS, "la sinopsis"),
            (lambda j, e, n: e.update(notaEdicion="a" * n), LARGO_NOTA_EDICION, "la nota de la edición"),
            (lambda j, e, n: j["parche"].update(notas="a" * n), LARGO_NOVEDADES, "las novedades"),
            (lambda j, e, n: e["parche"].update(notas="a" * n), LARGO_NOVEDADES, "las novedades"),
            (lambda j, e, n: e["versiones"][0].update(notas="a" * n), LARGO_NOVEDADES, "las novedades"),
            (lambda j, e, n: j["parche"].update(version="1" * n), LARGO_VERSION, "la versión"),
            (lambda j, e, n: e["versiones"][0].update(version="1" * n), LARGO_VERSION, "la versión"),
            (lambda j, e, n: e["huellasParcheadas"][0].update(version="1" * n), LARGO_VERSION, "la versión"),
        ]
        for cambiar, maximo, nombre in casos:
            self.assertEqual([], motivos(lambda j, e: cambiar(j, e, maximo)), nombre)
            pasado = motivos(lambda j, e: cambiar(j, e, maximo + 1))
            self.assertEqual(1, len(pasado), nombre)
            self.assertIn(nombre, pasado[0])
            self.assertIn(f"tiene {maximo + 1} caracteres y el máximo es {maximo}", pasado[0])

    def test_se_cuenta_como_el_parcheador(self):
        # Sin los espacios de los lados…
        self.assertEqual([], motivos(lambda j, e: j.update(sinopsis="  " + "a" * LARGO_SINOPSIS + "\n\n")))
        # … y en unidades UTF-16: un emoji de los nuevos cuenta dos.
        self.assertEqual([], motivos(lambda j, e: e.update(notaEdicion="😀" * (LARGO_NOTA_EDICION // 2))))
        self.assertEqual(1, len(motivos(lambda j, e: e.update(notaEdicion="😀" * (LARGO_NOTA_EDICION // 2) + "a"))))
        self.assertEqual([], motivos(lambda j, e: e.update(notaEdicion="ñ" * LARGO_NOTA_EDICION)))

    def test_vacio_o_sin_el_campo(self):
        self.assertEqual([], motivos(lambda j, e: (j.update(sinopsis=""), e.pop("notaEdicion"), j.pop("parche"))))

    def test_un_texto_enorme(self):
        self.assertEqual(1, len(motivos(lambda j, e: j.update(sinopsis="a" * 5_000_000))))

    def test_lo_que_ya_estaba_largo_no_bloquea_otras_propuestas(self):
        vieja = copy.deepcopy(BASE)
        vieja["juegos"][0]["sinopsis"] = "a" * (LARGO_SINOPSIS + 500)
        # Cambiar otra cosa vale…
        self.assertEqual([], motivos(lambda j, e: e.update(notaEdicion="Otra nota"), vieja))
        # … acortarla, aunque siga larga, no: lo que se escribe tiene que caber.
        self.assertEqual(1, len(motivos(lambda j, e: j.update(sinopsis="a" * (LARGO_SINOPSIS + 1)), vieja)))
        self.assertEqual([], motivos(lambda j, e: j.update(sinopsis="a" * LARGO_SINOPSIS), vieja))

    def test_un_juego_o_una_version_nuevos_tambien(self):
        def juego_nuevo(j, e):
            j["id"] = "juego2"  # para el robot es otro juego: todo su texto es nuevo
            j["sinopsis"] = "a" * (LARGO_SINOPSIS + 1)
        self.assertEqual(1, len(motivos(juego_nuevo)))
        self.assertEqual(1, len(motivos(lambda j, e: e["versiones"].append(
            {"version": "1.1.0", "estado": "pruebas", "notas": "a" * (LARGO_NOVEDADES + 1)}))))

    def test_formas_raras_no_rompen_el_robot(self):
        self.assertEqual([], comprobar_largos(None, BASE))
        self.assertEqual([], comprobar_largos("x", {"juegos": [None, 5, {"id": "j", "sinopsis": 7, "parche": "x",
                                                                         "ediciones": [None, {"id": "e", "versiones": [None, "x"]}]}]}))
        self.assertEqual(1, len(comprobar_largos(None, cambiado(lambda j, e: j.update(sinopsis="a" * 4001)))))


class EnUnaPropuesta(unittest.TestCase):
    def revisar(self, permisos, cambiar):
        return comprobar([Cambio(RUTA_CATALOGO, "M")], json.dumps(BASE), json.dumps(cambiado(cambiar)), permisos)

    def test_ni_el_propietario_se_salta_el_tope(self):
        salida = self.revisar(PROPIETARIO, lambda j, e: j.update(sinopsis="a" * (LARGO_SINOPSIS + 1)))
        self.assertEqual(1, len(salida))
        self.assertIn("la sinopsis tiene 4001 caracteres y el máximo es 4000", salida[0])

    def test_un_colaborador_dentro_del_tope_pasa(self):
        self.assertEqual([], self.revisar(COLABORADOR, lambda j, e: j.update(sinopsis="a" * LARGO_SINOPSIS)))

    def test_un_editor_con_una_nota_larga_no(self):
        self.assertEqual(1, len(self.revisar(EDITOR, lambda j, e: e.update(notaEdicion="a" * (LARGO_NOTA_EDICION + 1)))))


if __name__ == "__main__":
    unittest.main()
