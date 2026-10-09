# InnovaDerm Digest — AXA
**Type:** Carrier CG
**Generated:** 2026-05-22T12:48:41.837662
**Status:** success
**Queries:** 6/6 successful

---

## axa_cg_coverage
**Query:** Para la aseguradora AXA: ¿Qué dice el documento de Condiciones Generales sobre cobertura de medicamentos biológicos, medicamentos de especialidad, y programación de pago directo? Cita las cláusulas ex

Para la aseguradora **AXA**, el documento de Condiciones Generales detalla lo siguiente respecto a tus consultas:

**1. Medicamentos biológicos**
Se mencionan explícitamente, pero están **excluidos** de la póliza. En el apartado **V. Exclusiones (gastos no cubiertos)**, la cláusula **48** establece que no se cubrirán:
> "Las siguientes fórmulas o preparaciones y productos aun por prescripción médica: [...] **f. Medicamentos biológicos e insumos utilizados en Terapia celular.**" [1].

**2. Medicamentos de especialidad**
El documento los contempla dentro de la cobertura de cuidados en domicilio cuando estos requieren asistencia profesional para ser aplicados. En el apartado **III. Cobertura básica**, subsección **3. Cuidados en casa o fuera del Hospital**, la cláusula **a. Enfermería** indica:
> "...quedan cubiertos los montos correspondientes a honorarios de enfermería, legalmente autorizada para ejercer su profesión, que bajo prescripción del Médico tratante, sean necesarios para la administración de **Medicamentos que requieren manejo, preparación y/o administración especializados**..." [2].

**3. Programación de pago directo**
Estos conceptos se explican de forma separada y complementaria en el apartado **I. Definiciones** mediante las siguientes cláusulas exactas:
*   **Cláusula 29. Pago Directo:** "Proceso mediante el cual la Compañía realiza el pago al Prestador en Convenio, por la atención médica brindada a un Asegurado. En caso de que el Asegurado requiera y solicite la atención de los Prestadores en Convenio, podrá hacer uso de este servicio, previa autorización por escrito de la Compañía, quien efectuará el pago de los gastos cubiertos por la Póliza a los Prestadores en Convenio..." [3].
*   **Cláusula 34. Programación de Servicios:** "Beneficio que la Compañía puede otorgar, previo a la realización de cualquier intervención quirúrgica o Tratamiento médico cubierto, para el pago que se realizará directamente a los Prestadores en Convenio, mediante el cual se valora la procedencia de la Programación del Servicio y su pago, previa autorización y valoración por parte de la Compañía" [4].

Para ambos casos, las cláusulas precisan que el servicio de pago directo y programación únicamente se otorgará "siempre y cuando la Compañía cuente de manera oportuna con toda la información suficiente para determinar la procedencia o improcedencia del pago" [5, 6]. De no proporcionar esta información, la aseguradora estará impedida para realizarlos [5, 6].

**Extract fields:** biologics_covered, specialty_meds_covered, pago_directo_available, programacion_required

---

## axa_cg_financial
**Query:** Para la aseguradora AXA: ¿Cuál es la estructura financiera descrita en las Condiciones Generales? Incluye: tipo de deducible, rango de tope de coaseguro, moneda, y si hay coaseguro diferenciado para m

Para la aseguradora AXA, la estructura financiera descrita en sus Condiciones Generales se define de la siguiente manera:

*   **Tipo de deducible:** Se define como un monto fijo a cargo del Asegurado, el cual es elegido por el Contratante y aplica para cada siniestro (enfermedad o accidente) cubierto [1, 2]. Este concepto no es reembolsable ni compensable [2]. 
    *   *Cifras exactas:* Si el Asegurado se atiende por enfermedad mediante Pago Directo con prestadores en convenio, el deducible será el estipulado en la póliza **menos $2,500** [3]. En caso de accidente (tanto en Pago Directo como en Reembolso), el deducible es de **$0** [3, 4].
*   **Rango de tope de coaseguro:** El Tope de Coaseguro es el monto máximo que el Asegurado pagará por este concepto por cada enfermedad o accidente [5]. Sin embargo, el documento **no menciona un rango o cifra exacta**, ya que especifica que dicho límite es elegido al momento de la contratación y queda indicado explícitamente en la carátula de la póliza [6]. Cabe destacar que existen rubros donde **no aplica** este tope, como en el uso de equipo médico [7] o al acudir a hospitales fuera de convenio o de una gama hospitalaria mayor a la contratada [4, 8].
*   **Moneda:** Los valores del Contrato de Seguro están denominados en **Moneda Nacional**, y se especifica que la moneda en que se emitió el contrato no podrá ser modificada [9, 10]. Todos los pagos deben efectuarse en Moneda Nacional al tipo de cambio que publique el Banco de México [9]. La única excepción con cifras en otra moneda es la cobertura de Emergencia Médica en el Extranjero (EMER), que tiene una Suma Asegurada de **50,000 USD** y un deducible de **50 USD** [11], aunque el pago final de la reclamación también se realiza en Moneda Nacional [12].
*   **Coaseguro diferenciado para medicamentos ambulatorios:** Las Condiciones Generales **no establecen un coaseguro diferenciado** para los medicamentos adquiridos fuera del hospital. El texto indica que estos medicamentos se cubren mediante "Pago por Reembolso" [13]. En la modalidad de Reembolso, se estipula que simplemente aplica el coaseguro normal contratado ("Coaseguro: de la Póliza") [3]. 

A modo de contexto adicional, aunque no hay coaseguro diferenciado para medicamentos, la póliza sí menciona cifras exactas de coaseguros diferenciados para otros rubros específicos:
*   Enfermedad por Pago Directo (en convenio): Coaseguro de la póliza **menos 10%** [3].
*   Accidentes: Coaseguro de **0%** [4].
*   Renta o compra de Equipo Médico: Coaseguro del **20%** (sin tope) [7].
*   Ambulancia aérea: Coaseguro del **20%** [14].
*   Lesiones en nariz y/o senos paranasales por accidente: Coaseguro del **70%** si el asegurado tiene menos de un año de antigüedad, y del **50%** si tiene un año o más [15].
*   Hospital de mayor nivel: Se suma una penalización de **+10%, +20% o +30%** (sin tope) dependiendo del salto de nivel, y **+40%** (sin tope) si es fuera de convenio [8].

**Extract fields:** deducible_type, tope_coaseguro, coaseguro_meds_outpatient, moneda

---

## axa_cg_preexisting
**Query:** Para la aseguradora AXA: ¿Cómo maneja los padecimientos preexistentes? ¿Están permanentemente excluidos o hay vía de cobertura? ¿Existe rider opcional? ¿Aplica regla de 30 días para nuevas pólizas? ¿D

Para la aseguradora **AXA**, el manejo de los padecimientos preexistentes se establece de la siguiente manera:

*   **¿Cómo maneja los padecimientos preexistentes?**
    AXA define las "Enfermedades Preexistentes" como aquellas cuyo diagnóstico se haya realizado con anterioridad a la celebración del Contrato de Seguro [1]. Su preexistencia puede demostrarse si fue declarada al contratar, si consta en un expediente médico anterior a la póliza, mediante pruebas de laboratorio o gabinete, o si existen gastos previos documentados para su diagnóstico o tratamiento [2].

*   **¿Están permanentemente excluidos o hay vía de cobertura?**
    Están **permanentemente excluidos** [3, 4]. En la póliza no se establece ninguna vía, tabulador o excepción dentro de la cobertura básica que permita cubrirlos posteriormente.

*   **¿Existe rider opcional?**
    **No existe ningún rider** o cobertura adicional con costo que permita amparar los padecimientos preexistentes. Las únicas coberturas adicionales detalladas (Atención Médica en el Extranjero, Paquete de Beneficios Adicionales, Maternidad y Gastos Médicos Complementarios) no incluyen protección para enfermedades preexistentes [5-8]. 

*   **¿Aplica regla de 30 días para nuevas pólizas?**
    **Sí aplica**. AXA establece que toda enfermedad diagnosticada en el transcurso de los primeros **30 días de vigencia** de la póliza queda excluida (y es tratada en la práctica bajo las mismas condiciones de no cobertura), al igual que cualquier enfermedad donde el asegurado haya realizado gastos comprobables durante ese mismo lapso inicial [9]. Este periodo de espera de 30 días no se aplica en casos de renovación, ni cuando se trata de accidentes o urgencias médicas [10, 11].

*   **¿Después de cuántos meses de cobertura continua se cubren?**
    **No se cubren después de ningún periodo**. A diferencia de otras aseguradoras que otorgan cobertura para preexistencias tras un periodo de espera, en las condiciones de AXA la exclusión para las Enfermedades Preexistentes es absoluta y permanente, sin importar los meses de cobertura continua que alcance el asegurado [3, 4].

*   **Cláusulas exactas a citar:**
    *   Para la exclusión total: **Apartado V. Exclusiones (gastos no cubiertos), cláusula 1.** que indica textualmente que no se cubren "Enfermedades Preexistentes." [3, 4].
    *   Para la definición médica y legal: **Apartado I. Definiciones, cláusula 18. Enfermedades Preexistentes.** [1, 2].
    *   Para la regla de los primeros 30 días: **Apartado V. Exclusiones (gastos no cubiertos), cláusula 63.** [9, 10] y **Apartado VI. Cláusulas generales, cláusula 1. Cobertura del Contrato de Seguro, inciso b.** [11, 12].

**Extract fields:** preexisting_excluded, coverage_after_months, optional_rider, thirty_day_rule

---

## axa_cg_preauth
**Query:** Para la aseguradora AXA: ¿Qué procedimientos o medicamentos requieren preautorización? ¿Cuál es el plazo en días hábiles (nacional e internacional)? ¿Requiere Segunda Valoración Médica? ¿Para qué cond

Para la aseguradora **AXA**, las Condiciones Generales establecen las siguientes reglas respecto a tu consulta:

**Procedimientos, medicamentos y servicios que requieren preautorización (Programación de Servicios)**
AXA utiliza el término "Programación de Servicios" o "Pago Directo" para referirse a la preautorización y valoración de un gasto médico. Requieren autorización o programación previa expresa:
*   **Intervención de más de un especialista:** En un mismo evento quirúrgico, requiere autorización previa de la Compañía [1].
*   **Cuidados en casa (extensión):** El periodo inicial de enfermería es de 30 días; para extenderlo por 30 días más, debe estar justificado, programado y autorizado por AXA [2, 3].
*   **Trasplantes específicos:** El trasplante de córnea o de ligamentos y tendones de origen cadavérico **únicamente** se pagará mediante la programación de la cirugía [4].
*   **Equipo médico fuera del hospital:** La renta o compra de equipo médico domiciliario debe ser autorizada, programada y coordinada por la Compañía [5].
*   **Prótesis, órtesis y ayudas funcionales:** Su renta o compra requiere tener la aprobación previa de la Compañía [6].

**Plazo en días hábiles (nacional e internacional)**
Las Condiciones Generales de AXA **no establecen un plazo específico de días hábiles** para autorizar la Programación de Servicios (a diferencia de otras aseguradoras). La póliza únicamente especifica que este servicio se otorgará siempre y cuando la Compañía cuente **"de manera oportuna con toda la información suficiente"** para determinar si el pago procede o no [7]. 

**¿Requiere Segunda Valoración Médica?**
De acuerdo con las condiciones de la póliza de AXA proporcionadas, **no se requiere una Segunda Valoración Médica** para ninguna condición o padecimiento [8]. (Este requerimiento es específico de otras aseguradoras en tus documentos, pero no aplica para AXA).

**Documentos necesarios**
Para tramitar el pago, reembolso o solicitar la autorización, el Asegurado debe presentar la siguiente documentación:
*   Formatos y documentos correspondientes debidamente requisitados [9].
*   **Informes médicos y estudios** (laboratorio, gabinete, imagen) que justifiquen el diagnóstico, relacionados directamente con el Accidente o Enfermedad [9, 10].
*   **Comprobantes originales de los gastos** que cumplan con todas las disposiciones fiscales vigentes (no se aceptan notas de venta) [9].
*   **Para medicamentos:** Receta médica que incluya la indicación de uso, frecuencia, duración y dosificación, y que cumpla con el artículo 28 del Reglamento de Insumos para la Salud [11].
*   **Para terapias:** Facturas que corroboren el tratamiento e indiquen el número de sesiones reclamadas [12].
*   En general, para autorizar una programación, se exige entregar "toda la información necesaria para dictaminar la procedencia del pago" de manera oportuna [7]. 

**Cláusulas a consultar**
Puedes revisar esta información en las siguientes cláusulas del documento de AXA:
*   **Cláusula I. Definiciones:** Definición 29 (Pago Directo) [13, 14] y Definición 34 (Programación de Servicios) [7, 15].
*   **Cláusula III. Cobertura básica:** Apartados de Honorarios médicos [1], Cuidados en casa [2, 3], Trasplante de tejidos [4] y Dispositivos médicos [5, 6, 16].
*   **Cláusula VI. Cláusulas generales:** Cláusula 25 (Siniestros) [9, 17].

**Extract fields:** preauth_required, national_days, intl_days, segunda_valoracion, docs_required

---

## axa_cg_appeals
**Query:** Para la aseguradora AXA: ¿Cuál es la vía de apelación en caso de negativa de cobertura? ¿Tiene UNE? ¿La UNE suspende prescripción? ¿Usa CONAMED, arbitraje privado, o amigable composición? ¿Cuál es el 

Para la aseguradora AXA, de acuerdo con sus Condiciones Generales, la información sobre tus dudas es la siguiente:

*   **Vía de apelación (Controversias):** En caso de controversia o negativa, puedes hacer valer tus derechos ante la Unidad Especializada de Atención de Consultas y Reclamaciones de AXA (UNE), ante la CONDUSEF, someterte al arbitraje de la CONDUSEF o acudir ante los tribunales competentes [1, 2]. 
*   **UNE:** Sí, AXA cuenta con una Unidad Especializada de Atención a Clientes (UNE) [3].
*   **¿La UNE suspende prescripción?:** Sí, el término de prescripción (que es de 2 años) se suspende al interponer una reclamación ante la UNE de la Compañía, conforme a la Ley de Protección y Defensa al Usuario de Servicios Financieros (Cláusula 18) [4, 5].
*   **Uso de CONAMED, arbitraje privado o amigable composición:** AXA utiliza el arbitraje de la CONDUSEF [2]. Además, cuenta con un **Arbitraje privado** específico para cuando la compañía notifique la improcedencia de una reclamación alegando una **Enfermedad Preexistente**; en este caso, se designa a un médico de común acuerdo para que funja como árbitro privado y decida sobre el caso (Cláusula 29) [6, 7]. Las condiciones de AXA no mencionan a la CONAMED ni la "amigable composición".
*   **Plazo de notificación de siniestro:** Es obligación dar aviso por escrito a la compañía en el transcurso de los primeros **5 días hábiles** siguientes a que ocurra el accidente o enfermedad (Cláusula 25) [8].
*   **Plazo de liquidación:** La Compañía pagará la indemnización procedente dentro de los **30 días naturales** siguientes a la fecha en que reciba todas las pruebas e información requeridas para fundamentar la reclamación (Cláusula 26 y Cláusula 27) [9, 10].

**Extract fields:** notification_days, une_name, une_suspends, appeal_body, settlement_days

---

## axa_cg_dermatology
**Query:** Para la aseguradora AXA: ¿Hay exclusiones específicas para productos dermatológicos, cosméticos, o tratamientos de piel? ¿Se menciona acné, lesiones pigmentarias, o biológicos para dermatitis atópica?

Para la aseguradora **AXA**, las Condiciones Generales establecen las siguientes políticas y exclusiones respecto a tu consulta:

**1. Productos dermatológicos, cosméticos y tratamientos de piel**
Sí, existen exclusiones específicas. AXA no cubre gastos generados por fórmulas, preparaciones o productos **cosméticos y dermatológicos**, aun cuando estos hayan sido recetados por un médico [1]. Además, se excluyen de la cobertura los procedimientos o tratamientos que sean de carácter estético o cosmetológico [2].

**2. Acné, lesiones pigmentarias y medicamentos biológicos**
*   **Acné y dermatitis atópica:** El documento de AXA no hace una mención específica literal a las enfermedades "acné" o "dermatitis atópica".
*   **Lesiones pigmentarias:** Sí se mencionan explícitamente y están excluidas de la póliza. AXA no cubre el "tratamiento quirúrgico de lesiones pigmentarias de la piel conocidas como lunares o nevus" [3].
*   **Biológicos:** Aunque no se detalla la dermatitis atópica, la aseguradora excluye de forma general y estricta el pago de cualquier **medicamento biológico** e insumo utilizado en terapia celular, incluso si se cuenta con prescripción médica [1].

**3. ¿La Segunda Valoración aplica para lesiones de piel?**
No, las condiciones de AXA **no contemplan** una "Segunda Valoración" para autorizar o tratar lesiones de la piel. Para esta aseguradora, el tratamiento quirúrgico de lesiones pigmentarias (lunares o nevus) entra directamente como un gasto no cubierto o exclusión [3]. *(Nota: El beneficio de "Segunda Valoración Médica" exclusivo para lunares o nevus corresponde a Seguros Monterrey New York Life dentro de tus documentos).*

**Cláusulas de exclusión que sustentan esta información (Apartado V. Exclusiones):**
*   **Exclusión 21:** "Procedimientos o Tratamientos de carácter estético, cosmetológico, plástico..." [2].
*   **Exclusión 48:** "Las siguientes fórmulas o preparaciones y productos aun por prescripción médica: [...] **d.** Cosméticos y dermatológicos. [...] **f.** Medicamentos biológicos e insumos utilizados en Terapia celular" [1].
*   **Exclusión 56:** "Tratamiento quirúrgico de lesiones pigmentarias de la piel conocidas como lunares o nevus" [3].

**Extract fields:** derm_products_excluded, biologics_excluded, skin_segunda_val, cosmetic_excluded

---
