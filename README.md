# ParcheadorRance-Datos

Los datos públicos del **Parcheador Central Rance**: el programa que instala las traducciones al español
de los juegos de Rance. El programa no trae nada escrito dentro: todo lo que enseña (juegos, versiones,
textos, imágenes) sale de aquí.

Aquí **no hay nada de los juegos originales**. Los parches solo contienen las diferencias entre el juego
original y el traducido, y el catálogo solo tiene nombres de archivo, tamaños y «hashes» (una especie de
huella dactilar de cada archivo, con la que no se puede reconstruir el juego).

## Qué hay en este repositorio

| Sitio | Qué es |
|---|---|
| [`catalogo/catalogo.json`](catalogo/catalogo.json) | **El catálogo**: la lista de juegos, ediciones, versiones de parche, textos y etiquetas. Es lo que el parcheador descarga al abrirse. |
| `catalogo/juegos/<juego>/` | Las imágenes de cada juego (icono, banner, fondo, logo, portada). El catálogo las nombra con rutas relativas a `catalogo/`. |
| [Releases](../../releases) | Los **paquetes de parche** (`<juego>-<edición>-<versión>.zip`) y, más adelante, las versiones del propio parcheador. |
| [`robot/`](robot/) y [`.github/workflows/`](.github/workflows/) | El **robot de permisos**: revisa cada cambio propuesto y lo publica solo si quien lo hace tiene permiso. |
| [`pruebas/`](pruebas/) | El «Juego de prueba»: un juego inventado para probar el parcheador de principio a fin. |

## La dirección del catálogo

El parcheador descarga siempre esta dirección:

```
https://raw.githubusercontent.com/OrnizStudio/ParcheadorRance-Datos/main/catalogo/catalogo.json
```

Es la dirección «raw» del archivo en la rama `main`. Se eligió en lugar de GitHub Pages porque:

- **No hay paso intermedio que pueda fallar**: lo que hay en `main` es lo que se sirve. Con Pages, cada
  cambio pasa antes por una publicación que tarda y a veces falla, y el catálogo se quedaría viejo sin avisar.
- **Tarda unos 5 minutos** en verse un cambio (GitHub guarda una copia ese tiempo); Pages, unos 10.
- Pages queda libre para el panel web del equipo.

Esa dirección está escrita dentro del parcheador, así que **no se puede renombrar** el repositorio, la
rama `main`, la carpeta `catalogo/` ni el archivo sin sacar antes una versión nueva del parcheador.

## Cómo se publica un cambio

1. Se cambia `catalogo/catalogo.json` (y las imágenes, si toca).
2. **Se sube `versionCatalogo` en 1.** El parcheador solo usa un catálogo si su número es mayor que el que
   ya tiene; si no sube, nadie se entera del cambio.
3. Los Administradores pueden subirlo directamente a `main`. Los Editores y Colaboradores lo mandan como
   propuesta (pull request) y el robot la revisa y la publica sola.

Para publicar un parche nuevo:

1. Crear el paquete con `parcheador-publicador paquete …` (da el `.zip` y el texto para el catálogo).
2. Subir el `.zip` a una Release con la etiqueta `<juego>-<versión>` (por ejemplo `prueba-0.1.0`). Una
   Release por versión del parche; dentro va un `.zip` por edición.
3. Pegar en el catálogo el `paquete` (con la dirección del `.zip` en la Release, `tamano` y `hash`) y las
   huellas, y subir `versionCatalogo`.

Un `.zip` ya publicado **no se sustituye nunca**: el catálogo guarda su tamaño y su hash, y el parcheador
rechaza un archivo que no coincida. Si hay que corregir algo, se publica una versión nueva.

## Roles y robot de permisos

| Rol | Equipo de GitHub | Nivel en este repositorio | Qué puede cambiar |
|---|---|---|---|
| Propietario y Administrador | `administradores` | Admin | Todo. |
| Editor | `editores` | Escritura (*write*) | El contenido de los juegos **que ya existen**: ediciones, versiones (crearlas, publicarlas, retirarlas), textos, imágenes, etiquetas puestas, créditos. No puede dar de alta, quitar, publicar ni ocultar un juego entero, ni tocar el parcheador (`launcher`), el grupo, las etiquetas del catálogo o cualquier archivo fuera de `catalogo/`. |
| Colaborador | `colaboradores` | Clasificación (*triage*) | Solo, en juegos y versiones que ya existen: **textos y notas** (`sinopsis`, `notaEdicion`, `parche.notas`), **etiquetas** (poner y quitar las que existen) y **estado de la traducción** (`estado`, `progreso`, `contenido`). |

Cómo funciona:

- La rama `main` está protegida: nadie que no sea Administrador puede escribir en ella directamente. Los
  cambios llegan como propuesta y la comprobación **`permisos`** es obligatoria.
- El robot ([`robot/permisos.py`](robot/permisos.py)) mira qué archivos y qué campos del catálogo cambia la
  propuesta, y el rol de quien la hace. Si todo está permitido, **la publica sola en menos de un minuto**.
  Si no, deja un comentario en la propuesta explicando, en lenguaje claro, qué no puede aceptar y por qué.
- A todos, también a los Administradores que usen propuestas, les comprueba que el catálogo se pueda leer,
  que `versionCatalogo` suba, que las etiquetas usadas existan y que los paquetes lleven dirección `https`,
  tamaño y hash.
- Un borrador (*draft*) se comprueba pero no se publica hasta marcarlo como listo.
- Los Colaboradores no pueden crear ramas aquí: proponen desde una copia propia del repositorio (*fork*).
  Los Editores sí pueden crear ramas (necesitan escritura para subir paquetes a las Releases).
- Cuenta el rol más bajo entre quien abrió la propuesta y quien subió el último cambio.

Límites que conviene conocer:

- El robot sabe el rol por el **nivel de acceso** de cada cuenta en este repositorio, que es lo único que
  puede consultar sin una clave propia. Por eso cada equipo tiene un nivel distinto: no hay que cambiarlos.
- Un Editor tiene escritura, y con escritura una persona con conocimientos técnicos y mala intención
  podría saltarse la comprobación (por ejemplo, subiendo a una rama una automatización que la dé por
  buena). El robot evita errores y excesos, pero **el rol de Editor es para gente de confianza**. Todo
  queda en el historial con su autor y se puede deshacer. Un Colaborador no tiene esa posibilidad.
- Las reglas se prueban con `python -m unittest discover -s robot/pruebas`.

Preparado para más adelante (sin hacer): que cada juego tenga su líder y su equipo. Las reglas ya preguntan
el rol «en este juego»; bastará con que el robot lea los permisos de un archivo `equipo.json` (está
indicado dónde, en `leer_equipo` de `robot/permisos.py`).

## Contenido de pruebas

Los juegos, ediciones y versiones marcados con `"pruebas": true` **no los ve el público**: el parcheador
los quita al cargar el catálogo. Solo los ve el equipo. Mientras el parcheador no tenga inicio de sesión,
el equipo lo abre con el argumento `--equipo`:

```
ParcheadorRance.exe --equipo
```

Ojo: `pruebas` solo **oculta**, no protege. Este repositorio es público y cualquiera puede leer el catálogo
y descargar los paquetes de las Releases. No pongas en pruebas nada que no pueda verse.

### El «Juego de prueba»

Es un juego inventado (id `prueba`) para comprobar el parcheador de verdad sin tocar ningún juego real.
Para usarlo:

1. Descarga `juego-de-prueba-original.zip` de la Release [`prueba-0.1.0`](../../releases/tag/prueba-0.1.0)
   y descomprímelo donde quieras.
2. Abre el parcheador con `--equipo`, entra en «Juego de prueba» y añade esa carpeta.
3. Instala el parche, comprueba que `Datos/textos.dat` pasa a estar en español y que aparece
   `Fuentes/fuente-de-prueba.ttf`, y quítalo para ver que todo vuelve a como estaba.

«Jugar» no funciona con él: `JuegoDePrueba.exe` es un archivo de texto, no un programa.

Las carpetas se generan con [`pruebas/crear-juego-prueba.py`](pruebas/crear-juego-prueba.py) y salen
siempre idénticas, así que el paquete se puede volver a crear en cualquier equipo.
