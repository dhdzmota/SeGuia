#Seguía

Este es el repositorio del proyecto SeGuía, para el Social Data Challenge 4.0.



- Eje temático: Medio Ambiente
- Problemática: De acuerdo con un informe presentado por la NASA (NASA, 2021) y distintos estudios realizados por investigadores del Departamento de Ciencias Ambientales de la Universidad de Guadalajara (UDG) se identificó que, al mes de abril del 2021, 85% del territorio mexicano sufre condiciones de sequía, siendo Jalisco uno de los estados más afectados. Esto ha provocado el desabasto de agua en el Área Metropolitana de Guadalajara (AMG) la cual podría pasar de crítica a severa-extrema en el mediano plazo. Así mismo, a nivel nacional, el agotamiento de los recursos hídricos ha afectado de manera social y ambiental a lo largo del tiempo y de manera incremental. La insuficiencia de agua es factor decisivo para que los habitantes de una población migren, y esto se relaciona con a la escasez de la producción de la tierra, la cual se ve ligada a desnutrición y puede desarrollarse hasta ocasionar más problemas políticas e incluso guerras. (Velasco I, Ochoa, L. y Gutierrez, C, 2005). El problema en un futuro cercano se ve todavía más pesimista, debido a que se prevé que la disponibilidad relativa y temporal del agua disminuya, así como la oportunidad de su abasto, y esto ocurre al aumentar la población y la demanda de agua. Diversos estudios pronostican que para el 2025, solamente dos entidades de la república tendrán la disponibilidad necesaria, las demás entidades pueden sufrir estrés hídrico (Instituto Mexicano de Tecnología del Agua, 2013). 
- Hipótesis: Con un conjunto de variables temporales, se puede predecir con una precisión del 80% el suceso y la severidad de una sequía con dos meses de anticipación en municipios de la República Mexicana. 
- Fuente de los datos: Los datos principales fueron obtenidos de la plataforma de “Monitor de sequía en México” administrada por el servicio meteorológico nacional. Se tienen datos a nivel municipal donde hubo una afectación de al menos 40% de su territorio por una condición de sequía con intensidad variable (Servicio Meteorológico Nacional, 2021). El hipervínculo de los datos es el siguiente: https://smn.conagua.gob.mx/es/climatologia/monitor-de-sequia/monitor-de-sequia-en-mexico. 
- Propuesta preliminar de solución: En la actualidad se cuentan con modelos que, con ayuda de indicadores como el índice estandarizado de sequía pluviométrica  [IESP], pueden predecir la sucesión de sequías (Blanquero, R., Carrizosa, E. et al, 2012). Nosotros proponemos generar un modelo de inteligencia artificial supervisado de clasificación para realizar la predicción de la sucesión y la severidad de sequías en municipios de la República Mexicana con dos meses de anticipación. Se planteará utilizar un algoritmo de ensamble de árboles (XGBoost) debido a que se cuenta con datos tabulares y a que se ha demostrado que con esta técnica se han obtenido resultados de estado-del-arte en muchos problemas de aprendizaje automático, (Chen y Guestrin, 2016; Shwartz-Ziv, y Armon, 2021). Buscamos predecir específicamente el índice del Monitor de Sequía de los Estados Unidos (USDM Scale) que está determinado por distintas características metereológicas y geobiológicas (Servicio Meteorológico Nacional, 2021) tales como: 
-- Condiciones de déficit o exceso de precipitación, 
-- Grado de vegetación a través de la radiancia observada
-- Humedad del suelo con modelo hidrológico
-- Temperatura media
-- Porcentaje de disponibilidad de agua. 
Por lo tanto, utilizaremos variables meteorológicas, geobiológicas y sociodemográficas para realizar la predicción coherente lo más pertinentemente posible.
 

## Miembros del equipo:
### Daniel Hernández Mota

_Graduado de Nanotecnología y actualmente ejerciendo como Científico de datos en Kueski y mentor en Saturdays Ai. Con experiencia en técnicas de modelado a través de aprendizaje automático y mecanismos de inteligencia artificial._

### Ana Sofía López Zúñiga

_Graduada en Mercadotecnia con experiencia en la coordinación y la medición de los esfuerzos de marketing, como campañas, estudios de mercado, desarrollo de nuevos productos y formación interna. Actualmente laborando en Simple [A] en el puesto de  Marketing Operations para mejorar las experiencias digitales de los usuarios mediante el desarrollo de estrategias que combinan los datos de los clientes, la analítica y la edición de contenidos._

### Alan Jesús Cortés de la Torre

_Graduado de Ingeniería en Nanotecnología y actualmente laborando como Analista de Datos en Kueski. Con experiencia en investigación, automatización de tareas basadas en datos, transformación de datasets y calidad de datos._
	

### Maximiliano Bernal Temores

_Economista Ambiental de la Universidad de San Francisco. Candidato a Maestría en Economía y Política Ambiental de la Universidad de Duke con enfoque en Cambio Climático. Business Development Associate en Citizen Energy con experiencia en consultoría y abogacía legislativa ambiental._


###Guillermo León Silva Ocegueda

_Ingeniero en Desarrollo de Software por el CETI Colomos. Titulado por desempeño académico y graduado con mención honorífica. Con más de 5 años de experiencia profesional en el ramo; actualmente laborando para Oracle como software developer en el área de DB tools and integration con colaboradores alrededor del mundo._

### Referencias:

Blanquero, R, Carrizosa, E., Pita, M., Camarillo, J., y Álvarez, J. (2012) Modelo estadístico para la predicción del índice estandarizado de sequía pluviométrica (IESP) en Andalucía. 8º Congreso Internacional de la Asociación Española de Climatología At: Salamanca, España. Recuperado (en línea) el 30 de Julio del 2021 de: https://www.researchgate.net/publication/301548530_Modelo_estadistico_para_la_prediccion_del_indice_estandarizado_de_sequia_pluviometrica_IESP_en_Andalucia 

Chen T. y Guestrin, C. (2016) XGBoost: A Scalable Tree Boosting System. Procedimientos de la  22ava ACM SIGKDD Conferencia Internacional en Descubrimiento y Minería de datos. Páginas 785–794 DOI: https://doi.org/10.1145/2939672.2939785. Recuperado (en línea)  el 30 de Julio del 2021 de: https://dl.acm.org/doi/10.1145/2939672.2939785. 

Instituto Mexicano de Tecnología del Agua (2013) Agua, sequía y cambio climático. Gobierno de México. Recuperado (en línea) el 31 de Julio del 2021 de: https://www.gob.mx/imta/prensa/agua-sequia-y-cambio-climatico?idiom=es 

NASA (2021) Sequía generalizada en México. NASA Ciencia. Recuperado en línea el 31 de Julio del 2021 de: https://ciencia.nasa.gov/sequia-generalizada-en-mexico  

Servicio Meteorológico Nacional (2021). Monitor de sequía de México. Recuperado (en línea) el 28 de Julio del 2021 de https://smn.conagua.gob.mx/es/climatologia/monitor-de-sequia/monitor-de-sequia-en-mexico. 

Shwartz-Ziv, R y Armon, A. (2021) Tabular Data: Deep Learning is Not All You Need. IT AI Group, Intel. Recuperado (en línea) el 30 de Julio del 2021 de https://arxiv.org/pdf/2106.03253.pdf 

Velasco I., Ochoa, L., y Gutiérrez C. (2005) Sequía un problema de perspectiva y gestión. Instituto Mexicano de Tecnología del Agua. Región y sociedad vol.17 no.34 Hermosillo sep./dic. 2005. ISSN 1870-3925 Recuperado (en línea) de: http://www.scielo.org.mx/scielo.php?script=sci_arttext&pid=S1870-39252005000300002 


