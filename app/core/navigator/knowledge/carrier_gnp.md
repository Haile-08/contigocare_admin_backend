# InnovaDerm Digest — GNP
**Type:** Carrier CG
**Generated:** 2026-05-22T12:48:46.007543
**Status:** success
**Queries:** 6/6 successful

---

## gnp_cg_coverage
**Query:** Para la aseguradora GNP: ¿Qué dice el documento de Condiciones Generales sobre cobertura de medicamentos biológicos, medicamentos de especialidad, y programación de pago directo? Cita las cláusulas ex

Para la aseguradora GNP, de acuerdo con su documento de Condiciones Generales, la información sobre estos conceptos es la siguiente:

*   **Medicamentos biológicos:** **NE (No Especificado)**. El documento no hace mención explícita a la cobertura de "medicamentos biológicos".

*   **Medicamentos de especialidad (especializados):** El documento ampara los medicamentos especializados exclusivamente dentro de la cobertura básica como un servicio extrahospitalario programado. La cláusula exacta estipula que se cubren:
    > "**Únicamente los servicios extrahospitalarios que a continuación se mencionan: programación de tratamientos que incluyen medicamentos especializados**, rehabilitación física y pulmonar, alimentación parenteral, todo ello mediante la prescripción médica" [1, 2].

*   **Programación de pago directo:** GNP regula este beneficio bajo el concepto de "Programación de cirugías, tratamientos médicos y servicios", el cual está ligado intrínsecamente al pago directo. Las cláusulas exactas mencionan lo siguiente:
    > **Definición de Programación:** "Servicio solicitado por el Asegurado y otorgado por GNP, el cual consiste en confirmar el pago directo al prestador de servicios independiente con el cual ha celebrado un convenio, por la atención médica a los Asegurados que presenten enfermedades o accidentes cubiertos por este Contrato, **antes de que ocurra la intervención quirúrgica, tratamiento con hospitalización o cirugía ambulatoria**; así como para el manejo de servicios especiales de acuerdo a la valoración de GNP para casos que requieran manejo integral extrahospitalario" [3, 4].

    Además, en la sección de "¿Qué hacer en caso de reclamación?", se detallan las ventajas de esta programación:
    > "Si usted y su médico programan una Cirugía o Tratamiento (incluyendo Cirugías Ambulatorias con estancia menor a 24 horas en el hospital), obtiene grandes beneficios como: [...] **No desembolsar cantidad alguna de los gastos procedentes, ya que su seguro paga directamente al hospital en convenio y a los especialistas del Círculo Médico**" [5, 6].

**Extract fields:** biologics_covered, specialty_meds_covered, pago_directo_available, programacion_required

---

## gnp_cg_financial
**Query:** Para la aseguradora GNP: ¿Cuál es la estructura financiera descrita en las Condiciones Generales? Incluye: tipo de deducible, rango de tope de coaseguro, moneda, y si hay coaseguro diferenciado para m

Para la aseguradora GNP, la estructura financiera detallada en sus Condiciones Generales es la siguiente:

*   **Tipo de deducible:** Se define como una **cantidad fija** estipulada en la póliza (el primer gasto a cargo del Asegurado). Este deducible se aplica **una sola vez para cada enfermedad o accidente cubierto** [1, 2]. Una vez que los gastos de atención superan esta cantidad, comienza la obligación de pago de GNP [1, 2].
*   **Rango de tope de coaseguro:** El documento no estipula cifras exactas ni rangos predeterminados para el tope de coaseguro general. En su lugar, indica que el **monto máximo** que el Asegurado deberá pagar por este concepto vendrá **estipulado directamente en la carátula de la póliza y/o en el certificado individual**, y aplicará para cada accidente o enfermedad [3]. Como datos exactos que rigen de forma excepcional:
    *   Para el servicio de ambulancia aérea se aplica un coaseguro exacto del **20%**, el cual es independiente del tope máximo general [4].
    *   Para la cobertura de "Enfermedades Catastróficas en el Extranjero", el coaseguro será el mayor entre **10%** y el contratado en la cobertura básica, pero **no aplica tope de coaseguro** [5].
*   **Moneda:** Tanto el pago de las primas como las indemnizaciones se liquidan siempre en **moneda nacional**, sujetándose a la Ley Monetaria vigente [6]. Si se incurre en gastos amparados en el extranjero, los pagos se calculan en moneda nacional al tipo de cambio publicado por el Banco de México en el Diario Oficial de la Federación, tomando en cuenta la fecha exacta en la que se recibieron los servicios médicos [6, 7].
*   **Coaseguro diferenciado para medicamentos ambulatorios:** Las condiciones generales indican que los medicamentos adquiridos fuera del hospital están cubiertos siempre y cuando se presente la factura desglosada y la receta médica para tramitar su reembolso [8, 9]. Sin embargo, **no existe mención a ningún coaseguro diferenciado** (ni eliminación del mismo) para los medicamentos ambulatorios; por ende, estos se rigen por la estructura general de deducible y coaseguro aplicable a la póliza [10].

**Extract fields:** deducible_type, tope_coaseguro, coaseguro_meds_outpatient, moneda

---

## gnp_cg_preexisting
**Query:** Para la aseguradora GNP: ¿Cómo maneja los padecimientos preexistentes? ¿Están permanentemente excluidos o hay vía de cobertura? ¿Existe rider opcional? ¿Aplica regla de 30 días para nuevas pólizas? ¿D

Para la aseguradora **GNP**, el manejo de los padecimientos preexistentes en su póliza colectiva se establece de la siguiente manera:

*   **¿Cómo maneja los padecimientos preexistentes?**
    GNP los define como cualquier enfermedad o padecimiento que cumpla con alguno de los siguientes criterios antes de la celebración del contrato o del alta del asegurado en la póliza:
    1. Que haya sido declarado [1].
    2. Que en un expediente médico se determine su existencia a través del diagnóstico de un médico legalmente autorizado [1].
    3. Que haya sido diagnosticado mediante pruebas de laboratorio, gabinete o cualquier otro medio reconocido de diagnóstico [1, 2].
    4. Que existan gastos comprobables documentalmente para recibir un diagnóstico o tratamiento de dicha enfermedad [2].

*   **¿Están permanentemente excluidos o hay vía de cobertura?**
    Están **permanentemente excluidos**. Las condiciones generales establecen claramente que la póliza no cubre los gastos originados por padecimientos preexistentes, así como tampoco sus consecuencias o complicaciones [3]. Asimismo, la póliza indica que incluso en las enfermedades que tienen un periodo de espera de 12 meses (como hernias o padecimientos prostáticos), "Estos padecimientos no quedarán cubiertos si son preexistentes" [4, 5].

*   **¿Existe rider opcional?**
    En las condiciones generales de GNP proporcionadas **no existe ningún rider opcional** (beneficio o cláusula adicional) para dar cobertura a padecimientos preexistentes. Por el contrario, los beneficios adicionales disponibles (como la Cláusula de Emergencia en el Extranjero, Cláusula Familiar, Cláusula de Enfermedades Catastróficas en el Extranjero y Cláusula de Ampliación de Beneficios) indican en sus exclusiones particulares que los padecimientos preexistentes no están cubiertos [6-9].

*   **¿Aplica regla de 30 días para nuevas pólizas?**
    Las condiciones generales de GNP no aplican una regla de exclusión de 30 días para padecimientos de reciente inicio (a diferencia de otras aseguradoras). La única regla de 30 días mencionada se refiere al plazo administrativo que tienen las personas de nuevo ingreso a la colectividad para dar su consentimiento y ser dadas de alta sin que se les exijan requisitos médicos adicionales [10, 11]. 

*   **¿Después de cuántos meses de cobertura continua se cubren?**
    Al ser una exclusión definitiva, **no hay un periodo de meses** de cobertura continua tras el cual se cubran los padecimientos preexistentes en esta póliza [3].

*   **Cita la cláusula exacta:**
    *   La definición se encuentra en la **Sección I. Definiciones**, bajo el concepto de **"Padecimientos preexistentes"** [1].
    *   La exclusión de cobertura se encuentra en la **Sección III. Exclusiones a la cobertura básica y beneficios adicionales**, primer punto del listado: *"Padecimientos preexistentes, según se indica en el apartado de Definiciones, así como sus consecuencias y complicaciones"* [3].

**Extract fields:** preexisting_excluded, coverage_after_months, optional_rider, thirty_day_rule

---

## gnp_cg_preauth
**Query:** Para la aseguradora GNP: ¿Qué procedimientos o medicamentos requieren preautorización? ¿Cuál es el plazo en días hábiles (nacional e internacional)? ¿Requiere Segunda Valoración Médica? ¿Para qué cond

Para la aseguradora GNP, los procedimientos relacionados con la preautorización (denominada en la póliza como **Programación de cirugías, tratamientos médicos y servicios**) operan de la siguiente manera:

**¿Qué procedimientos o medicamentos requieren preautorización?**
Se debe programar el pago directo con GNP antes de que ocurran los siguientes eventos:
*   **Intervenciones quirúrgicas**, tratamientos con **hospitalización** o **cirugías ambulatorias** [1].
*   **Servicios extrahospitalarios** que requieran un manejo integral, los cuales incluyen: **medicamentos especializados**, rehabilitación física y pulmonar, y alimentación parenteral [2, 3].
*   Compra o renta de **auxiliares mecánicos** (ej. sillas de ruedas, camas ortopédicas) [3, 4].
*   Atenciones amparadas bajo la **Cláusula de Enfermedades Catastróficas en el Extranjero** [5].
*(Cláusulas: "I. Definiciones", "III. Cobertura básica - Gastos a cargo de GNP" y "XI. Beneficios adicionales").*

**Plazo en días hábiles (Nacional e Internacional)**
*   **Territorio Nacional:** La documentación debe entregarse al menos **5 días hábiles antes** de la cirugía o tratamiento en la Oficina de Servicio de GNP [6]. 
*   **Territorio Extranjero:** La documentación debe entregarse al menos **10 días hábiles antes** de la cirugía o tratamiento médico [7]. Este mismo plazo de **10 días hábiles** aplica para tratamientos bajo la Cláusula de Enfermedades Catastróficas en el Extranjero [5, 8].
*(Cláusula: "VII. ¿Qué hacer en caso de reclamación? - Programación de cirugías y tratamientos médicos").*

**¿Requiere Segunda Valoración Médica? ¿Para qué condiciones?**
En las Condiciones Generales de GNP proporcionadas, **no se estipula el requisito de una Segunda Valoración Médica** o Segunda Opinión Médica obligatoria para autorizar cirugías o padecimientos (a diferencia de otras aseguradoras en sus respectivas normativas). La autorización está sujeta únicamente a la evaluación del expediente, el dictamen de GNP y que el padecimiento esté amparado sin periodo al descubierto [1, 9-11].

**Documentos necesarios para la preautorización**
Para **Territorio Nacional**, se requiere presentar:
*   **Informe Médico** llenado en su totalidad por el médico tratante (si intervienen dos o más médicos, se debe entregar un informe por cada uno) [12].
*   **Aviso de Accidente o Enfermedad** de Programación de Cirugía llenado por el Asegurado [13].
*   **Receta médica** para medicamentos y/o material de curación (en caso de antibióticos, basta con copia simple) [12].
*   **Informe médico actualizado** cada 6 meses (para tratamientos prolongados) [12].
*   **Estudios preoperatorios**, de laboratorio o gabinete, junto con su interpretación [13].
*   Nombres de los integrantes del **equipo médico o quirúrgico**, su Registro Federal de Contribuyentes (RFC) y teléfonos de contacto [13].
*   **Presupuesto desglosado** por cada integrante del equipo médico o quirúrgico [6].
*   Para tratamientos, se debe indicar claramente el **número de sesiones** [6].

Para **Territorio Extranjero**, además de los informes y el aviso de accidente o enfermedad, se requiere **adicionalmente**:
*   **Historia clínica** del padecimiento actual [14].
*   Nombre del **hospital, ciudad y teléfono** en donde se practicará la intervención [14].
*   **Fecha** en la que se efectuará el tratamiento médico o quirúrgico [14].
*   Nombre, teléfono y clave del **RFC del médico que lo atendió en México** [7].
*(Cláusula: "VII. ¿Qué hacer en caso de reclamación? - Programación de cirugías y tratamientos médicos").*

**Extract fields:** preauth_required, national_days, intl_days, segunda_valoracion, docs_required

---

## gnp_cg_appeals
**Query:** Para la aseguradora GNP: ¿Cuál es la vía de apelación en caso de negativa de cobertura? ¿Tiene UNE? ¿La UNE suspende prescripción? ¿Usa CONAMED, arbitraje privado, o amigable composición? ¿Cuál es el 

Para la aseguradora **GNP**, de acuerdo con sus Condiciones Generales, aquí tienes las respuestas a tus preguntas junto con las cláusulas correspondientes:

*   **Vía de apelación en caso de negativa y uso de instancias (UNE/CONDUSEF):** 
    En caso de controversia o rechazo, el asegurado puede hacer valer sus derechos ante la **Unidad Especializada de Atención a Usuarios (UNE)** de GNP o ante la **CONDUSEF** [1, 2]. *(Cláusula: Competencia)*.
*   **¿Tiene UNE?** 
    **Sí**, GNP cuenta con una Unidad Especializada de Atención a Usuarios (UNE) [1, 3].
*   **¿La UNE suspende la prescripción?** 
    La póliza indica que la prescripción se interrumpirá y suspenderá en los casos y causas previstos por la *Ley de Protección y Defensa al Usuario de Servicios Financieros* [4], legislación bajo la cual operan tanto la UNE como la CONDUSEF. *(Cláusula: Prescripción)*.
*   **¿Usa CONAMED, arbitraje privado o amigable composición?** 
    GNP utiliza el **arbitraje privado** [5]. Específicamente, estipula que si se notifica la improcedencia de una reclamación por considerarse un "padecimiento preexistente", el reclamante puede optar por acudir a un arbitraje privado ante una persona física o moral designada de común acuerdo [5]. *Nota: A diferencia de otras aseguradoras en tus documentos, GNP no hace mención expresa al uso de la CONAMED ni a la figura de "amigable composición". (Cláusula: Arbitraje)*.
*   **Plazo de notificación de siniestro:** 
    El asegurado goza de un plazo máximo de **cinco días** para dar el aviso por escrito, el cual debe realizarse tan pronto como tenga conocimiento del siniestro [6, 7]. La cláusula no especifica textualmente si se trata de días hábiles o calendario (naturales), mencionando únicamente "cinco días" [6]. *(Cláusula: Periodo para informar la ocurrencia del siniestro)*.
*   **Plazo de liquidación (pago):** 
    GNP pagará los siniestros procedentes en un plazo no mayor a **30 días naturales**, contados a partir de la fecha de recepción de todos los documentos, datos e informes que le permitan dictaminar la indemnización [8, 9]. En caso de no cumplir con este plazo, la aseguradora deberá pagar una indemnización por mora [10]. *(Cláusulas: Pago de indemnizaciones / Indemnización por mora)*.

**Extract fields:** notification_days, une_name, une_suspends, appeal_body, settlement_days

---

## gnp_cg_dermatology
**Query:** Para la aseguradora GNP: ¿Hay exclusiones específicas para productos dermatológicos, cosméticos, o tratamientos de piel? ¿Se menciona acné, lesiones pigmentarias, o biológicos para dermatitis atópica?

Para la aseguradora **GNP**, de acuerdo con sus Condiciones Generales, la situación respecto a los temas dermatológicos y de la piel es la siguiente:

**1. Exclusiones de productos dermatológicos, cosméticos o tratamientos de piel**
Sí, existen exclusiones explícitas. La póliza de GNP excluye de manera directa los **"Gastos por productos dermatológicos, aunque sean médicamente necesarios o se encuentren prescritos por el médico tratante"** [1]. 

Además, dentro de las exclusiones a la cobertura básica, tampoco están cubiertos los **"Tratamientos médicos o quirúrgicos de tipo estético y de calvicie"** [2] (salvo complicaciones graves amparadas bajo la cobertura de "Emergencias de gastos médicos mayores no cubiertos" [2, 3]). 

También cabe destacar que, en caso de tener contratada la Cláusula de Enfermedades Catastróficas en el Extranjero, se encuentra expresamente excluido el **"Cáncer de piel"** [4].

**2. Acné, lesiones pigmentarias o biológicos para dermatitis atópica**
En el contrato de GNP **no se menciona** de forma específica el acné, las lesiones pigmentarias ni los medicamentos biológicos para la dermatitis atópica. Sin embargo, al existir la exclusión general para cualquier "producto dermatológico" [1], es muy probable que cualquier tratamiento enfocado estrictamente en la dermatología enfrente restricciones, independientemente de que no se nombren estas enfermedades exactas en el texto. *(Nota: Las lesiones pigmentarias y el acné sí son mencionados explícitamente en las pólizas de otras aseguradoras de tus fuentes, como SMNYL, Metlife y Axa, pero no en GNP).*

**3. Segunda Valoración para lesiones de piel**
**No**, las Condiciones Generales de GNP no contemplan ni mencionan el requisito de una "Segunda Valoración" para el tratamiento de lesiones de piel ni para ningún otro padecimiento. *(Nota: El requisito de "Segunda Valoración Médica" para lesiones pigmentarias de la piel es una regla que aplica específicamente para la aseguradora SMNYL [5], no para GNP).*

**Cláusulas de exclusión (Citas textuales de GNP)**

Dentro de la sección **"III. Exclusiones a la cobertura básica y beneficios adicionales"**:
*   "Gastos por productos dermatológicos, aunque sean médicamente necesarios o se encuentren prescritos por el médico tratante." [1]
*   "Tratamientos médicos o quirúrgicos de tipo estético y de calvicie, excepto lo específicamente mencionado en la cobertura Emergencias de gastos médicos mayores no cubiertos." [2]

Dentro de la **"Cláusula de Enfermedades Catastróficas en el Extranjero"** (Exclusiones adicionales a la cobertura básica):
*   "Cáncer de piel." [4]

**Extract fields:** derm_products_excluded, biologics_excluded, skin_segunda_val, cosmetic_excluded

---
