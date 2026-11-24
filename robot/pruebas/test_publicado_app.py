"""Fase C: lo que la rama `publicado` lleva para la app 0.3.0 (`juegos/`, `detalle/`, `canales/`, `logos/`,
`etiquetas.json` y las claves nuevas de `indice.json`), con los casos extremos."""

import copy
import hashlib
import json
import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import particion  # noqa: E402
import publicar  # noqa: E402
from test_particion import todo_el_modelo  # noqa: E402
import test_publicar  # noqa: E402
from test_publicar import MAIN, sueltos_de  # noqa: E402

AHORA = "2026-11-24T00:00:00Z"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
WEBP = b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 16


def canal_json(cid, estado="activo", logo=None, **otros):
    canal = {"esquema": 1, "id": cid, "nombre": cid.capitalize(), "descripcion": f"Canal {cid}",
             "contacto": {"issues": True}, "paquetes": [], "adultos": True, "normasAceptadas": 0,
             "creado": "2026-11-21", "estado": estado, "oculto": False,
             "verificacion": {"verificado": cid == "ornizen", "desde": "2026-11-21"}, **otros}
    if logo is not None:
        canal["logo"] = logo
    return particion.texto_json(canal)


def con_canales(archivos, *canales):
    archivos = dict(archivos)
    archivos["canales/ornizen/canal.json"] = canal_json("ornizen")
    for cid in canales:
        archivos[f"canales/{cid}/canal.json"] = canal_json(cid)
    return archivos


def parche(jid, **campos):
    return particion.texto_json({"esquema": 1, "juego": jid, **campos})


def publicados(archivos, catalogo=None):
    return publicar.archivos_publicados(archivos, catalogo, MAIN, AHORA)


def trozo(salida, carpeta, ident):
    return json.loads(salida[f"{carpeta}/{publicar.trozo(ident)}.json"])


def juego_de(salida, jid):
    return next(j for j in trozo(salida, "juegos", jid)["juegos"] if j["id"] == jid)


def canal_de(salida, cid):
    return next(c for c in trozo(salida, "canales", cid)["canales"] if c["id"] == cid)


class Formato(unittest.TestCase):
    def test_juego_detalle_y_canal(self):
        salida = publicados(con_canales(sueltos_de()), todo_el_modelo())
        juego = juego_de(salida, "rance-x")
        self.assertEqual("activo", juego["estado"])
        self.assertEqual(["ornizen"], [p["canal"] for p in juego["parches"]])
        entrada = juego["parches"][0]
        # El detalle: el juego de esquema 1 entero, con huellas y versiones; su hash es el de verdad.
        detalle = salida["detalle/rance-x/ornizen.json"]
        self.assertEqual("sha256:" + hashlib.sha256(detalle).hexdigest(), entrada["detalle"])
        completo = json.loads(detalle)
        self.assertEqual((1, "ornizen"), (completo["esquema"], completo["canal"]))
        esperado = next(j for j in particion.juntar(sueltos_de(), 0, todos=True)["juegos"] if j["id"] == "rance-x")
        self.assertEqual(esperado, completo["juego"])
        self.assertIn("huella", completo["juego"]["ediciones"][0])
        self.assertIn("huellasParcheadas", completo["juego"]["ediciones"][0])
        self.assertIn("versiones", completo["juego"]["ediciones"][0])
        # El ligero: lo mismo sin huellas ni versiones en ninguna edición.
        ligero = entrada["juego"]
        for edicion in ligero["ediciones"]:
            for campo in ("huella", "huellasParcheadas", "versiones"):
                self.assertNotIn(campo, edicion)
        self.assertEqual("Steam «ñ» 🎌", ligero["ediciones"][0]["nombre"])
        self.assertEqual(esperado["titulo"], ligero["titulo"])
        # Canal.
        canal = canal_de(salida, "ornizen")
        self.assertEqual({"id": "ornizen", "nombre": "Ornizen", "descripcion": "Canal ornizen", "verificado": True,
                          "adultos": True, "estado": "activo", "oculto": False, "contacto": {"issues": True},
                          "logo": None}, canal)
        # Índice: grupo, trozos nuevos con su hash, sin detalle ni logos en `trozos`.
        indice = json.loads(salida["indice.json"])
        self.assertEqual(1, indice["esquema"])
        self.assertEqual(todo_el_modelo()["grupo"], indice["grupo"])
        self.assertIn("etiquetas.json", indice["trozos"])
        self.assertEqual({"esquema": 1, "etiquetas": todo_el_modelo()["etiquetas"]}, json.loads(salida["etiquetas.json"]))
        for ruta, valor in indice["trozos"].items():
            self.assertEqual("sha256:" + hashlib.sha256(salida[ruta]).hexdigest(), valor)
        self.assertFalse([r for r in indice["trozos"] if r.startswith(("detalle/", "logos/"))])
        for ruta in salida:
            self.assertTrue(ruta == "indice.json" or ruta in indice["trozos"] or ruta.startswith(("detalle/", "logos/")), ruta)
        for datos in salida.values():
            self.assertTrue(datos.endswith(b"\n"))

    def test_la_fase_b_no_cambia(self):
        archivos = sueltos_de()
        antes = {r: d for r, d in publicados(archivos).items() if r.startswith("programa/")}
        despues = publicados(con_canales(archivos, "otro_canal"))
        self.assertEqual(antes, {r: d for r, d in despues.items() if r.startswith("programa/")})
        indice = json.loads(despues["indice.json"])
        self.assertEqual(1, indice["esquema"])
        for clave in ("generado", "main", "versionCatalogo", "launcher", "trozos", "grupo"):
            self.assertIn(clave, indice)

    def test_grupo_null_sin_grupo(self):
        archivos = sueltos_de(dict(todo_el_modelo(), grupo=None))
        archivos[particion.RUTA_PARCHEADOR] = particion.texto_json({"esquema": 1})
        self.assertIsNone(json.loads(publicados(archivos)["indice.json"])["grupo"])

    def test_dos_veces_lo_mismo_da_los_mismos_bytes(self):
        archivos = con_canales(sueltos_de(), "otro_canal")
        archivos["canales/otro_canal/parches/rance-x.json"] = parche("rance-x", titulo="Otro")
        archivos["canales/ornizen/logo.png"] = PNG
        archivos["canales/ornizen/canal.json"] = canal_json("ornizen", logo="logo.png")
        primera = publicados(archivos)
        segunda = publicados(dict(reversed(list(archivos.items()))))
        self.assertEqual(primera, segunda)
        self.assertEqual(publicar._sin_fecha(primera["indice.json"]),
                         publicar._sin_fecha(publicar.archivos_publicados(archivos, None, "b" * 40, "otra")["indice.json"]))
        # Cambia un detalle (solo una huella): cambia su hash, su trozo y el índice.
        edicion = json.loads(archivos["juegos/rance-x/ediciones/steam.json"])
        edicion["huella"] = []
        otra = publicados(dict(archivos, **{"juegos/rance-x/ediciones/steam.json": particion.texto_json(edicion)}))
        self.assertNotEqual(publicar._sin_fecha(primera["indice.json"]), publicar._sin_fecha(otra["indice.json"]))
        # Cambia solo el logo: cambia el trozo del canal y el índice.
        otra = publicados(dict(archivos, **{"canales/ornizen/logo.png": PNG + b"x"}))
        self.assertNotEqual(publicar._sin_fecha(primera["indice.json"]), publicar._sin_fecha(otra["indice.json"]))


class CasosExtremos(unittest.TestCase):
    def test_cinco_mil_juegos_y_cinco_mil_canales(self):
        base = todo_el_modelo()["juegos"][0]
        juegos = [dict(copy.deepcopy(base), id=f"juego-{i:05}") for i in range(5000)]
        archivos = sueltos_de({"esquema": 1, "versionCatalogo": 1, "juegos": juegos})
        canales = [f"canal_{i:05}" for i in range(5000)]
        archivos = con_canales(archivos, *canales)
        for i, cid in enumerate(canales):
            archivos[f"canales/{cid}/parches/juego-{i:05}.json"] = parche(f"juego-{i:05}", titulo=f"T {i}")
        inicio = time.monotonic()
        salida = publicados(archivos)
        self.assertLess(time.monotonic() - inicio, 20)
        self.assertTrue(all(len(d) <= publicar.TOPE_ARCHIVO for d in salida.values()))
        trozos_juegos = [r for r in salida if r.startswith("juegos/")]
        trozos_canales = [r for r in salida if r.startswith("canales/")]
        self.assertEqual((256, 256), (len(trozos_juegos), len(trozos_canales)))
        juegos_salida = [j for r in trozos_juegos for j in json.loads(salida[r])["juegos"]]
        self.assertEqual(5000, len(juegos_salida))
        self.assertTrue(all(len(j["parches"]) == 2 for j in juegos_salida))
        self.assertEqual(5001, sum(len(json.loads(salida[r])["canales"]) for r in trozos_canales))
        self.assertEqual(10000, len([r for r in salida if r.startswith("detalle/")]))
        for ruta in trozos_canales:
            for c in json.loads(salida[ruta])["canales"]:
                self.assertEqual(ruta, f"canales/{publicar.trozo(c['id'])}.json")

    def test_un_juego_con_cincuenta_canales(self):
        canales = [f"canal_{i:02}" for i in range(50)]
        archivos = con_canales(sueltos_de(), *canales)
        for cid in reversed(canales):
            archivos[f"canales/{cid}/parches/rance-x.json"] = parche("rance-x", titulo=f"Rance X en {cid}",
                                                                      ediciones=[{"id": "steam", "estado": "publico"}])
        salida = publicados(archivos)
        juego = juego_de(salida, "rance-x")
        self.assertEqual(sorted(["ornizen", *canales]), [p["canal"] for p in juego["parches"]])
        self.assertEqual("Rance X en canal_07", next(p for p in juego["parches"] if p["canal"] == "canal_07")["juego"]["titulo"])
        for p in juego["parches"]:
            self.assertEqual("sha256:" + hashlib.sha256(salida[f"detalle/rance-x/{p['canal']}.json"]).hexdigest(), p["detalle"])

    def test_logos(self):
        archivos = con_canales(sueltos_de(), "enorme", "falso", "sin_logo", "bueno_w", "bueno_j", "no_esta", "ruta_mala")
        casos = {
            "enorme": ("logo.png", b"\x89PNG\r\n\x1a\n" + b"\0" * (512 * 1024)),
            "falso": ("logo.png", b"GIF89a" + b"\0" * 20),
            "bueno_w": ("logo.webp", WEBP),
            "bueno_j": ("logo.jpeg", JPEG),
            "no_esta": ("logo.png", None),
            "ruta_mala": ("../ornizen/logo.png", None),
        }
        for cid, (nombre, datos) in casos.items():
            archivos[f"canales/{cid}/canal.json"] = canal_json(cid, logo=nombre)
            if datos is not None:
                archivos[f"canales/{cid}/{nombre}"] = datos
        archivos["canales/ornizen/logo.png"] = PNG  # existe pero el canal no lo nombra
        salida = publicados(archivos)
        for cid in ("enorme", "falso", "sin_logo", "no_esta", "ruta_mala", "ornizen"):
            self.assertIsNone(canal_de(salida, cid)["logo"], cid)
        self.assertEqual({"ruta": "logos/bueno_w.webp", "tamano": len(WEBP), "hash": "sha256:" + hashlib.sha256(WEBP).hexdigest()},
                         canal_de(salida, "bueno_w")["logo"])
        self.assertEqual("logos/bueno_j.jpg", canal_de(salida, "bueno_j")["logo"]["ruta"])
        self.assertEqual(WEBP, salida["logos/bueno_w.webp"])
        self.assertEqual(JPEG, salida["logos/bueno_j.jpg"])
        self.assertEqual(["logos/bueno_j.jpg", "logos/bueno_w.webp"], sorted(r for r in salida if r.startswith("logos/")))
        # Justo en el tope sí vale.
        justo = b"\x89PNG\r\n\x1a\n" + b"\0" * (512 * 1024 - 8)
        archivos["canales/enorme/logo.png"] = justo
        self.assertEqual(512 * 1024, canal_de(publicados(archivos), "enorme")["logo"]["tamano"])

    def test_canal_retirado_y_bloqueado(self):
        archivos = con_canales(sueltos_de())
        archivos["canales/viejo/canal.json"] = canal_json("viejo", estado="retirado")
        archivos["canales/malo/canal.json"] = canal_json("malo", estado="bloqueado")
        archivos["canales/viejo/parches/rance-x.json"] = parche("rance-x")
        archivos["canales/malo/parches/rance-x.json"] = parche("rance-x")
        archivos["canales/malo/parches/a.json"] = parche("a")  # su único parche es del bloqueado
        del archivos["canales/ornizen/parches/a.json"]
        salida = publicados(archivos)
        self.assertEqual(["ornizen", "viejo"], [p["canal"] for p in juego_de(salida, "rance-x")["parches"]])
        self.assertNotIn("detalle/rance-x/malo.json", salida)
        self.assertNotIn("a", [j["id"] for r in salida if r.startswith("juegos/") for j in json.loads(salida[r])["juegos"]])
        self.assertEqual("retirado", canal_de(salida, "viejo")["estado"])
        self.assertEqual("bloqueado", canal_de(salida, "malo")["estado"])

    def test_canal_danado_no_entra_ni_sus_parches(self):
        archivos = con_canales(sueltos_de())
        archivos["canales/sin_canal/parches/rance-x.json"] = parche("rance-x")
        archivos["canales/roto/canal.json"] = b"{"
        archivos["canales/roto/parches/rance-x.json"] = parche("rance-x")
        archivos["canales/otro_id/canal.json"] = canal_json("distinto")
        archivos["canales/raro/canal.json"] = canal_json("raro", estado="pausado")
        archivos["canales/MAYUS/canal.json"] = canal_json("MAYUS")
        archivos["canales/ab/canal.json"] = canal_json("ab")
        salida = publicados(archivos)
        ids = [c["id"] for r in salida if r.startswith("canales/") for c in json.loads(salida[r])["canales"]]
        self.assertEqual(["ornizen"], ids)
        self.assertEqual(["ornizen"], [p["canal"] for p in juego_de(salida, "rance-x")["parches"]])

    def test_juego_central_retirado_y_bloqueado(self):
        archivos = con_canales(sueltos_de())
        for jid, estado in (("a", "retirado"), ("b", "bloqueado"), ("prueba", "raro")):
            central = json.loads(archivos[f"juegos/{jid}/juego.json"])
            central["estado"] = estado
            archivos[f"juegos/{jid}/juego.json"] = particion.texto_json(central)
        salida = publicados(archivos)
        self.assertEqual("retirado", juego_de(salida, "a")["estado"])
        self.assertEqual("bloqueado", juego_de(salida, "b")["estado"])
        self.assertIsNone(juego_de(salida, "a")["parches"][0]["juego"]["ediciones"])
        self.assertEqual([], juego_de(salida, "b")["parches"][0]["juego"]["ediciones"])
        # Un estado central desconocido: el juego no entra (dato dañado), el resto sí.
        self.assertNotIn("detalle/prueba/ornizen.json", salida)
        self.assertIn("detalle/rance-x/ornizen.json", salida)

    def test_ids_raros(self):
        base = {"id": "x", "titulo": "X"}
        juegos = [dict(base, id=i) for i in ("Rance.Quest", "RANCE-01", "a.b_c-d", "9")]
        archivos = con_canales(sueltos_de({"esquema": 1, "versionCatalogo": 1, "juegos": juegos}))
        # Ids que no valen: no se publican aunque haya archivos con esas rutas.
        for malo in ("..", "con", "con.txt", "a..b", ".oculto", "-x", "x" * 101, "ñ"):
            archivos[f"juegos/{malo}/juego.json"] = particion.texto_json({"esquema": 1, "id": malo})
            archivos[f"canales/ornizen/parches/{malo}.json"] = parche(malo)
        archivos["canales/ornizen/parches/rance-x.json"] = parche("otro")  # el `juego` no es el nombre del archivo
        salida = publicados(archivos)
        ids = sorted(j["id"] for r in salida if r.startswith("juegos/") for j in json.loads(salida[r])["juegos"])
        self.assertEqual(["9", "RANCE-01", "Rance.Quest", "a.b_c-d"], ids)
        self.assertIn("detalle/Rance.Quest/ornizen.json", salida)
        for ruta in salida:
            self.assertNotIn("..", ruta)
            self.assertTrue(all(p and p not in (".", "..") for p in ruta.split("/")), ruta)

    def test_lo_danado_de_un_juego_no_tumba_el_resto(self):
        archivos = con_canales(sueltos_de(), "otro_canal")
        archivos["canales/otro_canal/parches/rance-x.json"] = parche("rance-x", ediciones=[{"id": "no-existe"}])
        archivos["juegos/a/juego.json"] = b"{"
        archivos["canales/otro_canal/parches/b.json"] = b"\xff"
        salida = publicados(archivos)
        self.assertEqual(["ornizen"], [p["canal"] for p in juego_de(salida, "rance-x")["parches"]])
        ids = [j["id"] for r in salida if r.startswith("juegos/") for j in json.loads(salida[r])["juegos"]]
        self.assertNotIn("a", ids)
        self.assertEqual(["ornizen"], [p["canal"] for p in juego_de(salida, "b")["parches"]])

    def test_un_detalle_de_mas_de_8_mb_para_la_publicacion(self):
        archivos = con_canales(sueltos_de())
        edicion = json.loads(archivos["juegos/rance-x/ediciones/steam.json"])
        edicion["huella"] = [{"ruta": f"archivo-{i:07}.dat", "hash": "blake3:" + "0" * 64} for i in range(90000)]
        archivos["juegos/rance-x/ediciones/steam.json"] = particion.texto_json(edicion)
        with self.assertRaises(publicar.ErrorPublicar) as error:
            publicados(archivos)
        self.assertIn("detalle/rance-x/ornizen.json", str(error.exception))
        self.assertIn("8 MB", str(error.exception))

    def test_sin_canales_ni_etiquetas(self):
        salida = publicados({})
        self.assertEqual(["indice.json"], list(salida))
        indice = json.loads(salida["indice.json"])
        self.assertEqual(({}, None), (indice["trozos"], indice["grupo"]))


class TrabajoConCanales(test_publicar.TrabajoEntero):
    def test_lee_canales_y_logos_de_main(self):
        catalogo = todo_el_modelo()
        archivos = con_canales(sueltos_de(catalogo))
        archivos["canales/ornizen/canal.json"] = canal_json("ornizen", logo="logo.webp")
        archivos["canales/ornizen/logo.webp"] = WEBP
        archivos["canales/grande/canal.json"] = canal_json("grande", logo="logo.png")
        archivos["canales/grande/logo.png"] = b"\x89PNG\r\n\x1a\n" + b"\0" * (600 * 1024)
        self.subir_main({**archivos, "catalogo/catalogo.json": particion.texto_json(catalogo)})
        _, _, escrito = self.correr()
        self.assertTrue(escrito)
        self.assertEqual(WEBP, self.del_remoto("publicado", "logos/ornizen.webp"))
        trozo_canal = json.loads(self.del_remoto("publicado", f"canales/{publicar.trozo('ornizen')}.json"))
        self.assertEqual("logos/ornizen.webp", trozo_canal["canales"][0]["logo"]["ruta"])
        grande = json.loads(self.del_remoto("publicado", f"canales/{publicar.trozo('grande')}.json"))
        self.assertIsNone(next(c for c in grande["canales"] if c["id"] == "grande")["logo"])
        detalle = self.del_remoto("publicado", "detalle/rance-x/ornizen.json")
        juegos = json.loads(self.del_remoto("publicado", f"juegos/{publicar.trozo('rance-x')}.json"))
        entrada = next(j for j in juegos["juegos"] if j["id"] == "rance-x")
        self.assertEqual("sha256:" + hashlib.sha256(detalle).hexdigest(), entrada["parches"][0]["detalle"])
        # Otra vez sin cambios: no escribe.
        _, _, escrito = self.correr()
        self.assertFalse(escrito)
        # Solo cambia el logo: escribe.
        self.subir_main({"canales/ornizen/logo.webp": WEBP + b"\0"})
        _, _, escrito = self.correr()
        self.assertTrue(escrito)

    def test_antes_de_la_migracion_con_canal_json(self):
        catalogo = todo_el_modelo()
        self.subir_main({"catalogo/catalogo.json": particion.texto_json(catalogo),
                         "canales/ornizen/canal.json": canal_json("ornizen")})
        _, _, escrito = self.correr()
        self.assertTrue(escrito)
        self.assertIn(b"rance-x", self.del_remoto("publicado", f"juegos/{publicar.trozo('rance-x')}.json"))


# Que las pruebas de `TrabajoEntero` no corran dos veces (por heredarlas aquí).
for _nombre in [n for n in vars(test_publicar.TrabajoEntero) if n.startswith("test_")]:
    setattr(TrabajoConCanales, _nombre, None)


if __name__ == "__main__":
    unittest.main()
