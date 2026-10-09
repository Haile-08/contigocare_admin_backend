# InnovaDerm Digest — MetLife
**Type:** Carrier CG
**Generated:** 2026-03-06T09:04:45.521393
**Status:** success
**Queries:** 6/6 successful

---

## metlife_cg_coverage
**Query:** Para la aseguradora MetLife: ¿Qué dice el documento de Condiciones Generales sobre cobertura de medicamentos biológicos, medicamentos de especialidad, y programación de pago directo? Cita las cláusula

Para la aseguradora MetLife, el documento de Condiciones Generales establece lo siguiente respecto a tus puntos de interés:

*   **Cobertura de medicamentos biológicos:** **NE (No Especificado)**. El documento no menciona explícitamente el término "medicamentos biológicos".
*   **Cobertura de medicamentos de especialidad:** **NE (No Especificado)**. El documento no utiliza de manera explícita el término "medicamentos de especialidad". Sin embargo, en el apartado de **Gastos Cubiertos, sección C. Medicamentos, cláusula 8**, establece de forma general la cobertura de medicinas: *"Medicamentos consumidos por el Asegurado en el hospital y los adquiridos fuera de él, siempre que sean prescritos por los médicos tratantes que tengan relación con el tratamiento del padecimiento cubierto y que estén registrados como medicamentos en la Secretaría de Salud"* [1].
*   **Programación de pago directo:**
    El documento aborda la programación y el pago directo a través de distintas cláusulas:
    *   **Definiciones, Cláusula 26 (Pago directo):** *"Mecanismo mediante el cual MetLife autoriza y liquida directamente al prestador de servicios médicos y/u hospitalarios los gastos procedentes, derivados de la atención médica del Asegurado por un padecimiento amparado por la póliza"* [2].
    *   **Definiciones, Cláusula 35 (Programación de cirugías):** Define el servicio previo como el *"Servicio mediante el cual MetLife confirma el pago directo al prestador de servicios médicos y hospitalarios afiliado y/o independiente, previo a la intervención quirúrgica y/o tratamiento con hospitalización o cirugía ambulatoria, en los términos de la póliza"* [3].
    *   **Gastos a cargo del asegurado, apartado B. Coaseguro, Cláusula 6 (Medicamentos fuera del hospital por pago directo):** Específicamente para la programación de medicinas, indica que *"Los medicamentos fuera del hospital que sean factibles de tramitar vía programación pago directo no aplicarán coaseguro"* [4].

**Extract fields:** biologics_covered, specialty_meds_covered, pago_directo_available, programacion_required

---

## metlife_cg_financial
**Query:** Para la aseguradora MetLife: ¿Cuál es la estructura financiera descrita en las Condiciones Generales? Incluye: tipo de deducible, rango de tope de coaseguro, moneda, y si hay coaseguro diferenciado pa

Para la aseguradora MetLife, la estructura financiera detallada en las Condiciones Generales de su producto Empresarial es la siguiente:

*   **Tipo de deducible:** Se define como una **cantidad inicial fija** que el asegurado debe cubrir y que se aplica **una sola vez por cada enfermedad o accidente** (es decir, por evento) al momento de realizarse el primer gasto [1, 2]. Como beneficio adicional, si se cuenta con el plan "Práctico", el deducible **puede reducirse en un 50%** si la atención se realiza en hospitales del mismo plan y se utilizan los servicios de pago directo o cirugía programada [3].

*   **Rango de tope de coaseguro:** Los topes máximos que el asegurado pagará por coaseguro están tabulados según el porcentaje contratado (que va del 5% al 25%) y el nivel hospitalario utilizado [4].
    *   **En hospitales del plan contratado:** El rango va desde **$12,650** (para un coaseguro del 5%) hasta **$63,250** (para un coaseguro del 25%) [4]. 
    *   **En hospitales de nivel superior o inferior al contratado:** El rango va desde **$50,600** (para un coaseguro del 10%) hasta **$127,050** (para un coaseguro del 25%) [4].
    *   Para porcentajes intermedios (entre el 5% y 20%), el tope se calcula sumando **$2,530** (en plan contratado) o **$5,060** (en plan superior/inferior) por cada 1% adicional de coaseguro [4].
    *   *Nota:* Si se tiene la cláusula de **cobertura en el extranjero**, los topes de coaseguro van desde **$50,600** (al 10%) hasta **$126,500** (al 25%) [5].

*   **Moneda:** Todos los pagos relativos al contrato se efectúan de manera predeterminada en **Moneda Nacional** (pesos mexicanos) conforme a la Ley Monetaria vigente [6]. No obstante, la póliza prevé explícitamente lineamientos de tipo de cambio aplicables en caso de que el contrato haya sido emitido en **dólares** [7].

*   **Coaseguro diferenciado para medicamentos ambulatorios:** Sí existe una diferenciación beneficiosa para el asegurado. La póliza especifica que los "Medicamentos fuera del hospital" **no aplicarán coaseguro** (es decir, es del 0%) siempre y cuando sean factibles de tramitarse a través de la modalidad de programación por **pago directo** [4, 8]. En los demás gastos como medicamentos adquiridos por reembolso regular, se aplica el coaseguro estipulado en la carátula de la póliza [9].

**Extract fields:** deducible_type, tope_coaseguro, coaseguro_meds_outpatient, moneda

---

## metlife_cg_preexisting
**Query:** Para la aseguradora MetLife: ¿Cómo maneja los padecimientos preexistentes? ¿Están permanentemente excluidos o hay vía de cobertura? ¿Existe rider opcional? ¿Aplica regla de 30 días para nuevas pólizas

Para la aseguradora MetLife, los padecimientos preexistentes se manejan de la siguiente manera:

*   **¿Cómo maneja los padecimientos preexistentes y están permanentemente excluidos?** 
    MetLife define una preexistencia como cualquier alteración de la salud que haya sido declarada, diagnosticada mediante un expediente o pruebas médicas, o por la cual el asegurado haya realizado gastos comprobables **previamente a la celebración del contrato** [1, 2]. **No están excluidos de forma permanente**; aunque en un inicio los gastos relacionados no están cubiertos, existe una vía de cobertura al cumplir con el periodo de espera establecido por la aseguradora [3, 4].
*   **¿Existe rider opcional?** 
    Las condiciones generales de la póliza no establecen la necesidad de contratar una cobertura opcional o *rider* para ampararlos. La cobertura de estos padecimientos se encuentra estipulada directamente dentro del apartado de la cobertura básica llamado "Eventos cubiertos sujetos a condiciones específicas" [3].
*   **¿Aplica regla de 30 días para nuevas pólizas?** 
    En las condiciones proporcionadas de MetLife, no se aplica una regla de exclusión de 30 días para determinar si una enfermedad nueva es preexistente. La definición de MetLife se limita estrictamente a las alteraciones de salud o gastos que hayan ocurrido *antes* del inicio de la póliza [1, 2]. 
*   **¿Después de cuántos meses de cobertura continua se cubren?** 
    Los padecimientos preexistentes quedan cubiertos después de **dos años (24 meses)** de que la persona haya estado asegurada de forma continua e ininterrumpida [3].
*   **Cláusula exacta:** 
    La regulación se encuentra en la sección *F. Eventos cubiertos sujetos a condiciones específicas*, inciso **34**, el cual indica textualmente:
    > "34. Los gastos que requiera el Asegurado por padecimientos preexistentes quedaran amparados una vez transcurridos dos años de estar Asegurado en forma continua e ininterrumpida en esta póliza, quedando excluido todo tipo de gasto presentado antes de cumplirse el periodo mencionado. Tratándose de miembros de nuevo ingreso a la colectividad asegurable, el periodo para tener derecho a este beneficio, se contará a partir de la fecha de inclusión como Asegurado en esta póliza." [3]

**Extract fields:** preexisting_excluded, coverage_after_months, optional_rider, thirty_day_rule

---

## metlife_cg_preauth
**Query:** Para la aseguradora MetLife: ¿Qué procedimientos o medicamentos requieren preautorización? ¿Cuál es el plazo en días hábiles (nacional e internacional)? ¿Requiere Segunda Valoración Médica? ¿Para qué 

Para la aseguradora **MetLife**, los lineamientos sobre preautorizaciones, tiempos, segundas valoraciones y documentos requeridos son los siguientes:

**1. Procedimientos o medicamentos que requieren preautorización (Programación de cirugías)**
La póliza define la **Programación de cirugías** como el servicio para confirmar el pago directo previo a cualquier intervención quirúrgica, tratamiento con hospitalización o cirugía ambulatoria [1]. 
Requieren obligatoriamente una valoración y autorización previa por parte de MetLife:
*   Las **Enfermedades Catastróficas en el Extranjero** (cáncer, enfermedades neurológicas y cerebrovasculares, cirugía de coronarias y trasplantes) [2, 3].
*   Tratamientos de **hernias, eventraciones y diástasis** (requieren previa valoración médica) [4].
*   Procedimientos quirúrgicos de las **glándulas mamarias** [5].
*   Cirugías por **adherencias pélvicas y endometriosis** [6].

**2. Plazo en días hábiles (nacional e internacional)**
*   **Internacional:** Para la cobertura de Enfermedades Catastróficas en el Extranjero, se debe solicitar la autorización por lo menos **10 días hábiles** antes de la atención médica [3].
*   **Nacional:** *Las condiciones generales provistas en las fuentes de MetLife no especifican un plazo exacto en días hábiles para la programación de cirugías a nivel nacional.*

**3. Segunda Valoración Médica y condiciones aplicables**
**Sí la requiere.** Se define como el proceso donde el asegurado debe corroborar su diagnóstico o procedimiento mediante un médico especialista designado por MetLife, sin costo para el asegurado (cláusula *Definiciones, inciso 50*) [7]. 

Las condiciones que están estrictamente sujetas a una Segunda Valoración Médica (cláusula *Gastos Cubiertos, inciso 36*) son [8]:
*   **Traumatología y ortopedia:** Cirugía de rodilla, cirugía de columna, hernias de disco intervertebral, clínica del dolor y sesiones de fisioterapia en general [9].
*   **Oncología:** Quimioterapia en cáncer de mama y quimioterapia en cirugía de colon [9].
*   **Otorrinolaringología:** Cirugías para determinar si son funcionales o estéticas por desviación de septum nasal o por hipertrofia de cornetes [9].
*   **Oftalmología:** Eventos realizados en dos tiempos, como cataratas y retinopatía [9]. *Adicionalmente*, las intervenciones para corrección de la vista (miopía, hipermetropía y astigmatismo) requieren de una segunda opinión médica [10].
*   **Cirugía general:** Hernias abdominales e inguinales [11].

**4. Documentos necesarios**
De acuerdo con la cláusula de *Siniestros o pago de reclamaciones (cláusula 18)* y las condiciones específicas de *Gastos Cubiertos*, se requiere la siguiente documentación:
*   **Generales:** Formas de reclamación correspondientes totalmente requisitadas, comprobantes originales que reúnan requisitos fiscales, radiografías y resultados de laboratorio/gabinete que incluyan los datos de identificación del asegurado [12, 13].
*   **Por condiciones específicas:**
    *   *Nariz y/o senos paranasales:* Tomografía y/o radiografías realizadas antes de la cirugía, así como fotografías de antes y después del procedimiento [4].
    *   *Padecimientos de glándulas mamarias, útero y ovarios:* Ultrasonido y mastografía (en su caso) [5].
    *   *Tratamientos dentales o maxilofaciales por accidente:* Radiografías post-traumáticas [14].
    *   *Complicaciones del embarazo (embarazo extrauterino, mola hidatiforme, toxicosis gravídica):* Ultrasonografía y/o estudio histopatológico [15, 16].
    *   *Placenta previa:* Ultrasonografía obligatoria [16].
    *   *Accidentes o delitos (ej. daño psiquiátrico por asalto/violación):* Copia certificada de las actuaciones o el acta levantada ante el Ministerio Público [13, 17].
    *   *Corrección de la vista:* Estudio de paquimetría, topometría y autorefractómetro [10].

**Extract fields:** preauth_required, national_days, intl_days, segunda_valoracion, docs_required

---

## metlife_cg_appeals
**Query:** Para la aseguradora MetLife: ¿Cuál es la vía de apelación en caso de negativa de cobertura? ¿Tiene UNE? ¿La UNE suspende prescripción? ¿Usa CONAMED, arbitraje privado, o amigable composición? ¿Cuál es

De acuerdo con las Condiciones Generales de **MetLife**, a continuación se detallan las respuestas a tus preguntas:

*   **Vías de apelación y esquema de resolución (CONAMED / Arbitraje / Amigable composición):** 
    En caso de que MetLife notifique la improcedencia (negativa) de una reclamación argumentando un "padecimiento preexistente", el reclamante puede optar por acudir a un **arbitraje médico privado** previo acuerdo entre las partes [1]. Este procedimiento arbitral se establece mediante la firma de un convenio arbitral bajo el esquema de **amigable composición** [2]. Adicionalmente, para cualquier controversia general, el asegurado puede hacer valer sus derechos ante la **UNE** de la aseguradora o ante la **CONDUSEF** [3, 4].
*   **Existencia de la UNE y Suspensión de la prescripción:** 
    Sí, MetLife cuenta con una **Unidad Especializada (UNE)** [3]. La interposición de una reclamación ante esta unidad **sí suspende el plazo de prescripción** de las acciones legales (mientras que la reclamación ante la CONDUSEF o el nombramiento de peritos la *interrumpe*) [5].
*   **Plazo de notificación de siniestro:** 
    La póliza estipula en su Cláusula 18 que es obligación del asegurado dar aviso por escrito de cualquier padecimiento [6]. Conforme a la Ley Sobre el Contrato de Seguro (Artículo 66) transcrita en la póliza, el plazo máximo para dar este aviso es de **5 días** contados a partir del momento en que se tenga conocimiento del siniestro [7, 8]. Al no especificar que son días hábiles, legalmente se entienden como días naturales.
*   **Plazo de liquidación (pago):** 
    Según la Cláusula 19, las reclamaciones e indemnizaciones procedentes serán liquidadas en un plazo de **30 días naturales** siguientes a la fecha en que MetLife haya recibido todos los documentos y la información necesaria para fundamentar la reclamación [9].

**Cláusulas y secciones citadas:**
*   **Definición 25:** Padecimiento preexistente (regula el arbitraje y la amigable composición) [1, 2].
*   **Cláusula 8:** Competencia (regula la UNE y CONDUSEF) [3, 4].
*   **Cláusula 10:** Prescripción (regula la suspensión por la UNE) [5].
*   **Cláusula 18:** Siniestros o pago de reclamaciones [6].
*   **Cláusula 19:** Pago de reclamaciones y/o indemnizaciones [9].
*   **Anexo 1.1:** Ley Sobre el Contrato de Seguro, Artículos 66 y 71 [7, 8, 10].

**Extract fields:** notification_days, une_name, une_suspends, appeal_body, settlement_days

---

## metlife_cg_dermatology
**Query:** Para la aseguradora MetLife: ¿Hay exclusiones específicas para productos dermatológicos, cosméticos, o tratamientos de piel? ¿Se menciona acné, lesiones pigmentarias, o biológicos para dermatitis atóp

Para la aseguradora **MetLife**, de acuerdo con sus Condiciones Generales, te detallo la información sobre tus consultas:

**1. Exclusiones para productos dermatológicos, cosméticos o tratamientos de piel y mención de acné:**
Sí, existen exclusiones explícitas para cuestiones estéticas y específicamente para el acné. En la sección de **Exclusiones (Apartado A. Padecimientos o tratamientos no cubiertos, inciso 8)**, se establece que la póliza no cubre:
* *"Tratamientos o intervenciones quirúrgicas de carácter estético o plástico, así como tratamientos médicos o quirúrgicos para corregir la calvicie, tratamientos dietéticos, la reducción o aumento de peso, la obesidad, anorexia y bulimia, y **acné**..."* [1].

Sin embargo, existe una excepción en caso de complicaciones graves. En la sección de **Gastos Cubiertos (inciso 35)** se indica que MetLife sí cubre las "Emergencias de gastos médicos no cubiertos". Esto significa que se amparan los gastos en territorio nacional derivados de complicaciones por intervenciones de carácter estético, plástico o por tratamientos para corregir el acné, **únicamente** mientras dure el estado de emergencia médica [2, 3]. 

*(Nota: La palabra "dermatológicos" o "cosméticos" como tal no aparece en la lista literal de MetLife, pero todo tratamiento estético y el acné están expresamente excluidos [1])*

**2. Lesiones pigmentarias y medicamentos biológicos para dermatitis atópica:**
Dentro del documento de MetLife **no se hace ninguna mención** específica a las "lesiones pigmentarias" (como nevus o lunares) ni al uso de "biológicos" o tratamientos para la "dermatitis atópica" [1, 4, 5]. Al no estar expresamente excluidos, su cobertura dependería de que cumplan con la definición general de "enfermedad" y no recaigan en la exclusión de fines "estéticos" o "preventivos" [1, 6, 7].

**3. ¿La Segunda Valoración Médica aplica para lesiones de piel?**
**No aplica.** Según la póliza de MetLife (sección de **Gastos Cubiertos, inciso 36**), los únicos procedimientos que quedan sujetos de forma obligatoria a una Segunda Valoración Médica pertenecen a las siguientes especialidades [3, 4, 8]:
* **Traumatología y ortopedia:** Cirugía de rodilla, columna, hernias de disco, fisioterapia, clínica del dolor.
* **Oncología:** Quimioterapia en cáncer de mama o colon.
* **Otorrinolaringología:** Cirugía de septum nasal o cornetes.
* **Oftalmología:** Eventos en dos tiempos (cataratas, retinopatía).
* **Cirugía general:** Hernias abdominales e inguinales.
No se incluye ninguna lesión de la piel ni procedimientos dermatológicos en este requisito [4, 8].

**Extract fields:** derm_products_excluded, biologics_excluded, skin_segunda_val, cosmetic_excluded

---
