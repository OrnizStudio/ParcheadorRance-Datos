"""Fase D, entrega 2: la lista negra general troceada, los nombres reservados y la regla de la verificación
(docs/canales.md §3 y §7.1). `robot/listas.py`, integrado en `permisos.comprobar` y `canales.comprobar_canales`.
"""

import datetime
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import listas  # noqa: E402
import particion  # noqa: E402
from permisos import Permisos, Rol  # noqa: E402
from test_fase_d_canales import OTRO, PARCHE_ES, canal_json, de, juzgar, main_con_dos_canales, version_nueva  # noqa: E402
from test_sueltos import HOY, JUEGO, YO, Propuesta, alta  # noqa: E402

DUENO = 1
HASH_MALO = "blake3:" + "d" * 64
CANAL_ES = f"canales/{OTRO}/canal.json"
MIEMBROS_ES = f"canales/{OTRO}/miembros.json"


def usuarios(*filas):
    trozos = {}
    for fila in filas:
        trozos.setdefault(listas.ruta_usuario(fila["id"]), []).append(fila)
    return {ruta: particion.texto_json({"esquema": 1, "usuarios": fs}) for ruta, fs in trozos.items()}


def veto(cuenta_id, motivo="Abusos", hasta=None):
    fila = {"id": cuenta_id, "cuenta": f"c{cuenta_id}", "motivo": motivo, "fecha": "2026-11-20"}
    if hasta:
        fila["hasta"] = hasta
    return fila


def huellas(*hashes):
    trozos = {}
    for h in hashes:
        trozos.setdefault(listas.ruta_huella(h), []).append(
            {"hash": h, "motivo": "Malware conocido", "fecha": "2026-11-20", "tipo": "paquete"})
    return {ruta: particion.texto_json({"esquema": 1, "huellas": fs}) for ruta, fs in trozos.items()}


def canales_bloqueados(*ids):
    return {listas.RUTA_CANALES: particion.texto_json({"esquema": 1, "canales": [
        {"id": i, "esqueleto": listas.canales.esqueleto(i), "motivo": "Publica malware", "fecha": "2026-11-20"}
        for i in ids]})}


def dueno():
    return Permisos(Rol.DUENO, cuenta_id=DUENO)


def con(main, **extra):
    main = dict(main)
    for archivos in extra.values():
        main.update(archivos)
    return main


def miembros_es(*filas):
    return {"esquema": 1, "miembros": [
        {"id": YO, "cuenta": "yo", "rol": "propietario", "desde": "2026-11-01", "estado": "activo"}, *filas]}


def con_miembros_es(main):
    return con(main, m={MIEMBROS_ES: particion.texto_json(miembros_es())})


def canal_es(nombre="Rance en Español", verificado=False):
    return canal_json(nombre=nombre, verificado=verificado)


class Trozos(unittest.TestCase):
    def test_el_trozo_es_el_sha256_de_la_clave(self):
        self.assertEqual("8b", listas.trozo(1234567))  # sha256("1234567")
        self.assertEqual(listas.trozo("1234567"), listas.trozo(1234567))
        self.assertEqual(listas.trozo(HASH_MALO), listas.trozo(HASH_MALO.upper()))
        self.assertRegex(listas.ruta_usuario(5), r"normas/lista-negra/usuarios/[0-9a-f]{2}\.json")

    def test_distancia_uno(self):
        self.assertTrue(listas.distancia_uno("rancetrad", "rancetrod"))
        self.assertTrue(listas.distancia_uno("rancetrad", "rancetra"))
        self.assertTrue(listas.distancia_uno("rancetrad", "rancetrads"))
        self.assertFalse(listas.distancia_uno("rancetrad", "rancetrodd"))
        self.assertFalse(listas.distancia_uno("abc", "xyz"))


class CuentasVetadas(unittest.TestCase):
    def propuesta(self, main):
        return Propuesta(main).cambiar(PARCHE_ES, lambda q: q["ediciones"][0].update(notaEdicion="x"))

    def test_una_cuenta_vetada_no_propone_nada(self):
        p = self.propuesta(con(main_con_dos_canales(), u=usuarios(veto(YO, "Spam"))))
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO}))
        self.assertEqual(1, len(motivos))
        self.assertIn("lista negra del programa (Spam)", motivos[0])

    def test_un_veto_que_ya_paso_no_cuenta(self):
        p = self.propuesta(con(main_con_dos_canales(), u=usuarios(veto(YO, hasta="2026-11-23"))))
        self.assertEqual([], juzgar(p, de({OTRO: Rol.PROPIETARIO})))
        p = self.propuesta(con(main_con_dos_canales(), u=usuarios(veto(YO, hasta=HOY.isoformat()))))
        self.assertTrue(juzgar(p, de({OTRO: Rol.PROPIETARIO})))

    def test_vale_tambien_para_quien_subio_un_cambio(self):
        from permisos import comprobar
        p = self.propuesta(con(main_con_dos_canales(), u=usuarios(veto(777))))
        texto = particion.texto_json({"esquema": 1, "versionCatalogo": 31, "juegos": []}).decode()
        lados = {"antes": p.antes, "despues": p.despues}
        motivos = comprobar(p.cambios(), texto, texto.encode(), de({OTRO: Rol.PROPIETARIO}),
                            leer_archivo=lambda r, lado: lados[lado].get(r), leer_sueltos=lambda lado: lados[lado],
                            hoy=HOY, cuentas=[YO, 777])
        self.assertTrue(any("777" in m and "lista negra del programa" in m for m in motivos), motivos)

    def test_otra_cuenta_del_mismo_trozo_no_cuenta(self):
        otro = next(i for i in range(2, 10 ** 6) if listas.trozo(i) == listas.trozo(YO) and i != YO)
        p = self.propuesta(con(main_con_dos_canales(), u=usuarios(veto(otro))))
        self.assertEqual([], juzgar(p, de({OTRO: Rol.PROPIETARIO})))

    def test_el_dueno_no_esta_nunca_vetado(self):
        p = self.propuesta(con(main_con_dos_canales(), u=usuarios(veto(DUENO))))
        self.assertEqual([], juzgar(p, dueno()))

    def test_un_trozo_roto_en_main_no_deja_pasar(self):
        main = con(main_con_dos_canales())
        main[listas.ruta_usuario(YO)] = b"{roto"
        motivos = juzgar(self.propuesta(main), de({OTRO: Rol.PROPIETARIO}))
        self.assertTrue(any("no se puede leer" in m for m in motivos), motivos)

    def test_un_vetado_no_entra_como_miembro(self):
        main = con_miembros_es(con(main_con_dos_canales(), u=usuarios(veto(555, "Suplantación"))))
        p = Propuesta(main).poner(MIEMBROS_ES, miembros_es(
            {"id": 555, "cuenta": "c555", "rol": "editor", "desde": "2026-11-24", "estado": "invitado",
             "invitadoPor": YO}))
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO}))
        self.assertTrue(any("lista negra del programa (Suplantación)" in m for m in motivos), motivos)


class CanalesBloqueados(unittest.TestCase):
    def test_nadie_salvo_el_dueno_toca_un_canal_bloqueado(self):
        main = con(main_con_dos_canales(), b=canales_bloqueados(OTRO))
        p = Propuesta(main).cambiar(PARCHE_ES, version_nueva())
        motivos = juzgar(p, de({OTRO: Rol.PROPIETARIO}))
        self.assertEqual(1, len(motivos))
        self.assertIn("@rance_es está bloqueado", motivos[0])
        self.assertFalse([m for m in juzgar(p, dueno()) if "bloqueado" in m])

    def test_no_se_veta_un_canal_verificado_en_main(self):
        main = con(main_con_dos_canales(), c={CANAL_ES: particion.texto_json(canal_es(verificado=True))})
        p = Propuesta(main)
        p.despues.update(canales_bloqueados(OTRO))
        motivos = juzgar(p, dueno())
        self.assertTrue(any("@rance_es está verificado: quítale antes la verificación" in m for m in motivos), motivos)
        # Quitarle la verificación en la misma propuesta no vale: se mira `main`.
        p.poner(CANAL_ES, canal_es())
        self.assertTrue(any("quítale antes la verificación" in m for m in juzgar(p, dueno())))
        # Sin verificar en `main`, sí.
        p2 = Propuesta(main_con_dos_canales())
        p2.despues.update(canales_bloqueados(OTRO))
        self.assertEqual([], juzgar(p2, dueno()))

    def test_el_dueno_no_se_veta_y_cada_cuenta_va_en_su_trozo(self):
        from permisos import comprobar
        p = Propuesta(main_con_dos_canales())
        p.despues.update(usuarios(veto(DUENO)))
        texto = particion.texto_json({"esquema": 1, "versionCatalogo": 31, "juegos": []}).decode()
        lados = {"antes": p.antes, "despues": p.despues}
        motivos = comprobar(p.cambios(), texto, texto.encode(), dueno(), leer_archivo=lambda r, lado: lados[lado].get(r),
                            leer_sueltos=lambda lado: lados[lado], hoy=HOY, ids_duenos=frozenset({DUENO}))
        self.assertTrue(any("Dueño del programa y no se puede vetar" in m for m in motivos), motivos)
        p = Propuesta(main_con_dos_canales())
        otro_trozo = next(t for t in ("00", "01", "02") if t != listas.trozo(YO))
        p.poner(f"normas/lista-negra/usuarios/{otro_trozo}.json", {"esquema": 1, "usuarios": [veto(YO)]})
        self.assertTrue(any(f"va en `usuarios/{listas.trozo(YO)}.json`" in m for m in juzgar(p, dueno())))

    def test_cinco_mil_canales_vetados_como_mucho(self):
        ids = [f"c{i:05d}" for i in range(5001)]
        p = Propuesta(main_con_dos_canales())
        p.despues.update(canales_bloqueados(*ids[:5000]))
        self.assertEqual([], juzgar(p, dueno()))
        p.despues.update(canales_bloqueados(*ids))
        self.assertTrue(any("el máximo son 5000" in m for m in juzgar(p, dueno())))


class HuellasVetadas(unittest.TestCase):
    def test_un_paquete_con_huella_vetada_por_el_programa(self):
        main = con(main_con_dos_canales(), h=huellas(HASH_MALO))
        p = Propuesta(main).cambiar(PARCHE_ES, version_nueva(huella=HASH_MALO))
        motivos = juzgar(p, de({OTRO: Rol.EDITOR}))
        self.assertTrue(any("lista negra (del programa: Malware conocido)" in m for m in motivos), motivos)

    def test_una_edicion_con_un_hash_vetado_no_se_da_de_alta(self):
        main = con(Propuesta().antes, h=huellas(HASH_MALO))
        p = Propuesta(main).cambiar(JUEGO, lambda j: j["ediciones"].append("gog"))
        p.poner("juegos/rance/ediciones/gog.json", {
            "esquema": 1, "id": "gog", "nombre": "GOG", "alta": alta(),
            "huella": [{"ruta": "Rance.exe", "tamano": 10, "hashParcial": HASH_MALO, "hash": HASH_MALO}]})
        motivos = juzgar(p, Permisos(Rol.ADMINISTRADOR, por_canal={"ornizen": Rol.ADMINISTRADOR}, cuenta_id=YO))
        self.assertTrue(any("la huella de la edición lleva" in m for m in motivos), motivos)


class HuellasEnElManifiesto(unittest.TestCase):
    """§1.2 y §4.3: la lista negra de huellas se mira también en los archivos que escribe el paquete."""

    def zip_con_destino(self, destino):
        import io
        import zipfile
        memoria = io.BytesIO()
        with zipfile.ZipFile(memoria, "w") as z:
            z.writestr("manifiesto.json", json.dumps({
                "esquema": 1, "juego": "rance", "edicion": "steam", "version": "1.1.0",
                "operaciones": [{"ruta": "a.dll", "tipo": "nuevo", "archivo": "nuevos/0", "destino": "blake3:" + "1" * 64},
                                {"ruta": "b.dll", "tipo": "diff", "origen": HASH_MALO, "diff": "d/1",
                                 "variantes": [{"cuando": {}, "destino": destino, "diff": "d/1"}]}]}))
            z.writestr("nuevos/0", b"x")
        return memoria.getvalue()

    def juzgar_con_paquete(self, main, destino):
        import hashlib
        import io
        from permisos import comprobar, rutas_del_paquete
        from test_fase_d_canales import URL_ES
        from test_prohibidos import Sha256EnLugarDeBlake3
        from test_sueltos import CATALOGO
        datos = self.zip_con_destino(destino)
        url = URL_ES.replace("rance-es.zip", "v2.zip")
        p = (Propuesta(main).cambiar(PARCHE_ES, version_nueva(url, "blake3:" + hashlib.sha256(datos).hexdigest()))
             .cambiar(PARCHE_ES, lambda q: q["ediciones"][0]["versiones"][-1]["paquete"].update(tamano=len(datos))))
        texto = particion.texto_json(CATALOGO).decode("utf-8")
        lados = {"antes": p.antes, "despues": p.despues}
        return comprobar(p.cambios(), texto, texto.encode(), de({OTRO: Rol.EDITOR}),
                         leer_paquete=lambda q: rutas_del_paquete(q, calcular_hash=Sha256EnLugarDeBlake3,
                                                                  abrir=lambda u: io.BytesIO(datos)),
                         leer_archivo=lambda r, lado: lados[lado].get(r), leer_sueltos=lambda lado: lados[lado],
                         hoy=HOY)

    def test_un_archivo_vetado_por_el_programa(self):
        main = con(main_con_dos_canales(), h=huellas(HASH_MALO))
        motivos = self.juzgar_con_paquete(main, HASH_MALO.upper().replace("BLAKE3", "blake3"))
        self.assertTrue(any("escribe un archivo" in m and "del programa" in m for m in motivos), motivos)

    def test_un_archivo_vetado_por_su_canal(self):
        main = main_con_dos_canales()
        main[f"canales/{OTRO}/lista-negra.json"] = particion.texto_json(
            {"esquema": 1, "archivos": [], "usuarios": [],
             "huellas": [{"hash": HASH_MALO, "motivo": "Minero", "fecha": "2026-11-20"}]})
        motivos = self.juzgar_con_paquete(main, HASH_MALO)
        self.assertTrue(any("escribe un archivo" in m and "@rance_es" in m for m in motivos), motivos)

    def test_el_origen_es_del_juego_y_no_cuenta(self):
        # `origen` (el archivo original del juego) lleva el hash vetado, pero el paquete no lo escribe.
        main = con(main_con_dos_canales(), h=huellas(HASH_MALO))
        self.assertEqual([], self.juzgar_con_paquete(main, "blake3:" + "2" * 64))


class Nombres(unittest.TestCase):
    def renombrar(self, nombre, main=None, reservados=None):
        main = con_miembros_es(main or main_con_dos_canales())
        if reservados is not None:
            main[listas.RUTA_RESERVADOS] = particion.texto_json({"esquema": 1, "nombres": reservados})
        return juzgar(Propuesta(main).poner(CANAL_ES, canal_es(nombre)), de({OTRO: Rol.PROPIETARIO}))

    def test_un_nombre_normal_vale(self):
        self.assertEqual([], self.renombrar("Traducciones Rance ES"))

    def test_nada_que_se_parezca_a_orniz(self):
        for nombre in ("Ornizen", "0rnizen fans", "Orn1z", "Оrnizen"):  # la última, con O cirílica
            with self.subTest(nombre):
                self.assertTrue(self.renombrar(nombre))

    def test_nombres_reservados_del_archivo(self):
        motivos = self.renombrar("S0porte", reservados=["Soporte", "Moderación"])
        self.assertTrue(any("reservado" in m for m in motivos), motivos)
        self.assertEqual([], self.renombrar("Rance Fans", reservados=["Soporte"]))

    def test_igual_que_otro_canal_o_a_una_letra_de_uno_verificado(self):
        main = main_con_dos_canales()
        main["canales/rancetrad/canal.json"] = particion.texto_json(
            canal_json("rancetrad", "Rance Traducciones", [], verificado=True))
        self.assertTrue(any("@rancetrad" in m for m in self.renombrar("Rance Traducciones", main)))
        self.assertTrue(any("@rancetrad" in m for m in self.renombrar("Rance Traduccione", main)))
        self.assertTrue(any("@rancetrad" in m for m in self.renombrar("rancetrad", main)))
        self.assertEqual([], self.renombrar("Rance Doblajes", main))

    def test_ni_al_de_un_canal_bloqueado(self):
        main = con(main_con_dos_canales(), b=canales_bloqueados("malware_es"))
        self.assertTrue(any("@malware_es" in m for m in self.renombrar("Malware ES", main)))


if __name__ == "__main__":
    unittest.main()


class ConfundiblesDeUnicode(unittest.TestCase):
    """UTS #39 (`robot/confusables.txt`, 16.0.0) además de nuestra tabla: las letras de la revisión N6."""

    def test_cada_letra_de_la_revision(self):
        import canales
        casos = {"ƶ": "Orniƶ", "ɾ": "Oɾniz", "ɳ": "Orɳiz", "ɨ": "Ornɨz", "ʐ": "Orniʐ", "lisu": "ꓳꓣꓠꓲꓜ",
                 "copto": "Ⲟrniz", "bengalí": "০rniz", "cirílico": "Oгniz"}
        for letra, nombre in casos.items():
            with self.subTest(letra):
                self.assertTrue(canales.nombre_reservado(nombre), canales.esqueleto(nombre))

    def test_los_nombres_normales_no_cambian(self):
        import canales
        self.assertEqual("rancefans", canales.esqueleto("Rancé Fans"))
        self.assertFalse(canales.nombre_reservado("Traducciones Rance ES"))

    def test_el_archivo_tiene_su_sha256_fijado(self):
        import hashlib
        import canales
        datos = canales.RUTA_CONFUSABLES.read_bytes()
        self.assertEqual(canales.SHA256_CONFUSABLES, hashlib.sha256(datos).hexdigest())
        self.assertIn(b"# Version: 16.0.0", datos[:400])
