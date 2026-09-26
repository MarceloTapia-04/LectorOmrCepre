const $ = (selector) => document.querySelector(selector);
const state = { 
  batch: null, 
  current: null, 
  image: null, 
  grid: true,
  students: [],
  filteredStudents: [],
  highlightedStudentIndex: -1,
  answerKey: {}
};
const canvas = $('#canvas');
const ctx = canvas.getContext('2d');
const optionLetters = 'ABCDE';

function center(question, option) {
  const block = Math.floor((question - 1) / 35);
  const row = (question - 1) % 35;
  const origins = [[636.6, 208.6], [788.6, 208.6], [946.6, 209.4], [1100.2, 210.2]];
  return { x: origins[block][0] + option * 19.5, y: origins[block][1] + row * 19.2 };
}

function calibratedPoint(question, option) {
  const point = center(question, option);
  if (!state.current?.grid_calibration) return point;
  const block = Math.floor((question - 1) / 35);
  const row = (question - 1) % 35;
  const [topLeft, topRight, bottomLeft, bottomRight] = state.current.grid_calibration.slice(block * 4, block * 4 + 4);
  const horizontal = option / 4;
  const vertical = row / 34;
  const top = { x: topLeft.x + horizontal * (topRight.x - topLeft.x), y: topLeft.y + horizontal * (topRight.y - topLeft.y) };
  const bottom = { x: bottomLeft.x + horizontal * (bottomRight.x - bottomLeft.x), y: bottomLeft.y + horizontal * (bottomRight.y - bottomLeft.y) };
  return { x: top.x + vertical * (bottom.x - top.x), y: top.y + vertical * (bottom.y - top.y) };
}

function message(target, text) { $(target).textContent = text; }
async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || 'No se pudo completar la operación.'); }
  return response.headers.get('content-type')?.includes('application/json') ? response.json() : response;
}

const UPLOAD_CHUNK_SIZE = 30; // 30 archivos por paquete para fluidez y cero timeouts

async function uploadFilesPipeline(fileList, isAddToBatch = false) {
  const allFiles = Array.from(fileList);
  const totalFiles = allFiles.length;
  if (totalFiles === 0) return;

  const chunks = [];
  for (let i = 0; i < totalFiles; i += UPLOAD_CHUNK_SIZE) {
    chunks.push(allFiles.slice(i, i + UPLOAD_CHUNK_SIZE));
  }
  const totalChunks = chunks.length;

  const startProgress = $('#start-progress');
  const startProgressFill = $('#start-progress-fill');
  const startProgressPct = $('#start-progress-pct');
  const startProgressSub = $('#start-progress-subtext');

  const wsProgress = $('#workspace-upload-progress');
  const wsProgressFill = $('#workspace-progress-fill');
  const wsProgressPct = $('#workspace-progress-pct');
  const wsProgressSub = $('#workspace-progress-subtext');

  function updateProgressUI(doneFiles, total) {
    const pct = Math.min(100, Math.round((doneFiles / total) * 100));
    if (!isAddToBatch && $('#start') && !$('#start').hidden) {
      if (startProgress) {
        startProgress.hidden = false;
        if (startProgressFill) startProgressFill.style.width = `${pct}%`;
        if (startProgressPct) startProgressPct.textContent = `${pct}%`;
        if (startProgressSub) startProgressSub.textContent = `Procesados ${doneFiles} de ${total} exámenes...`;
      }
    }
    if (wsProgress) {
      wsProgress.hidden = false;
      if (wsProgressFill) wsProgressFill.style.width = `${pct}%`;
      if (wsProgressPct) wsProgressPct.textContent = `${pct}%`;
      if (wsProgressSub) wsProgressSub.textContent = `Procesados ${doneFiles} de ${total} exámenes...`;
    }
  }

  let processedCount = 0;

  if (!isAddToBatch) {
    $('#upload').disabled = true;
    updateProgressUI(0, totalFiles);

    const firstChunk = chunks[0];
    const formData = new FormData();
    for (const f of firstChunk) formData.append('files', f);

    message('#upload-status', `Iniciando lote con primeros ${firstChunk.length} exámenes...`);
    const batch = await request('/api/batches', { method: 'POST', body: formData });
    state.batch = batch;
    processedCount += firstChunk.length;
    updateProgressUI(processedCount, totalFiles);

    $('#start').hidden = true;
    $('#workspace').hidden = false;
    renderBatch();
    if (batch.sheets.length > 0) {
      await openSheet(batch.sheets[0].id);
    }

    for (let c = 1; c < totalChunks; c++) {
      const chunk = chunks[c];
      const chunkData = new FormData();
      for (const f of chunk) chunkData.append('files', f);

      message('#viewer-status', `Procesando exámenes: paquete ${c + 1} de ${totalChunks} (${processedCount}/${totalFiles})...`);
      const result = await request(`/api/batches/${state.batch.id}/sheets`, {
        method: 'POST',
        body: chunkData,
      });
      state.batch.sheets = result.sheets;
      processedCount += chunk.length;
      updateProgressUI(processedCount, totalFiles);
      renderBatch();
    }

    message('#viewer-status', `✅ ¡Lote completado! ${state.batch.sheets.length} exámenes cargados con éxito.`);
    setTimeout(() => {
      if (wsProgress) wsProgress.hidden = true;
      if (startProgress) startProgress.hidden = true;
    }, 3500);
  } else {
    const btnUploadMore = $('#btn-upload-more');
    if (btnUploadMore) {
      btnUploadMore.disabled = true;
      btnUploadMore.textContent = 'Subiendo exámenes...';
    }
    updateProgressUI(0, totalFiles);

    const initialCount = state.batch.sheets.length;
    for (let c = 0; c < totalChunks; c++) {
      const chunk = chunks[c];
      const chunkData = new FormData();
      for (const f of chunk) chunkData.append('files', f);

      message('#viewer-status', `Añadiendo exámenes: paquete ${c + 1} de ${totalChunks} (${processedCount}/${totalFiles})...`);
      const result = await request(`/api/batches/${state.batch.id}/sheets`, {
        method: 'POST',
        body: chunkData,
      });
      state.batch.sheets = result.sheets;
      processedCount += chunk.length;
      updateProgressUI(processedCount, totalFiles);
      renderBatch();
    }

    if (btnUploadMore) {
      btnUploadMore.disabled = false;
      btnUploadMore.textContent = '➕ Subir más exámenes';
    }
    const addedTotal = state.batch.sheets.length - initialCount;
    message('#viewer-status', `✅ Se agregaron ${addedTotal} exámenes. Total en el lote: ${state.batch.sheets.length}.`);
    setTimeout(() => {
      if (wsProgress) wsProgress.hidden = true;
    }, 3500);
  }
}

$('#files').addEventListener('change', () => {
  const count = $('#files').files.length;
  $('#upload').disabled = count === 0;
  message('#upload-status', count ? `${count} archivo(s) seleccionado(s) listos para procesar.` : '');
});

$('#upload').addEventListener('click', async () => {
  try {
    await uploadFilesPipeline($('#files').files, false);
  } catch (error) {
    message('#upload-status', error.message);
    alert('Error al procesar lote: ' + error.message);
    $('#upload').disabled = false;
    const startProgress = $('#start-progress');
    if (startProgress) startProgress.hidden = true;
  }
});

function renderBatch() {
  const sheets = state.batch.sheets;
  const approved = sheets.filter((sheet) => sheet.status === 'approved').length;
  $('#batch-summary').textContent = `${approved}/${sheets.length} aprobadas`;
  $('#export').disabled = approved === 0;
  const exportDetailedBtn = $('#export-detailed');
  if (exportDetailedBtn) exportDetailedBtn.disabled = approved === 0;
  const resultsExportDetailedBtn = $('#btn-results-export-detailed');
  if (resultsExportDetailedBtn) resultsExportDetailedBtn.disabled = approved === 0;
  $('#sheet-list').replaceChildren(...sheets.map((sheet, index) => {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.className = `sheet ${state.current?.id === sheet.id ? 'active' : ''}`;
    const marked = (sheet.counts.ok || 0) + (sheet.counts.manual || 0);
    const blank = sheet.counts.blank || 0;
    const multiple = (sheet.counts.multiple || 0) + (sheet.counts.uncertain || 0);
    const studentInfo = sheet.student ? `<span class="sheet-student-sub" title="${escapeHtml(sheet.student)}">👤 ${escapeHtml(sheet.student)}</span>` : '';
    const isPass = (sheet.score !== undefined ? sheet.score : 0) >= 50;
    const scoreInfo = (sheet.score !== undefined && (sheet.status === 'approved' || sheet.score !== 0))
      ? `<span class="sheet-score-pill ${isPass ? 'score-high' : 'score-low'}" title="Nota del examen: ${sheet.score.toFixed(2)} pts (${isPass ? 'Aprobado' : 'Desaprobado'})">🎯 Nota: ${sheet.score.toFixed(2)} pts</span>`
      : '';
    button.innerHTML = `
      <span class="sheet-name">${index + 1}. ${escapeHtml(sheet.source_name)}${sheet.page_number ? ` · p. ${sheet.page_number}` : ''}</span>
      ${studentInfo}
      ${scoreInfo}
      <span class="sheet-meta">
        <span>${marked} marcadas · ${blank} vacías · ${multiple} doble</span>
        <span class="tag ${sheet.status}">${sheet.status === 'approved' ? 'aprobada' : 'revisar'}</span>
      </span>
    `;
    button.onclick = () => openSheet(sheet.id);
    item.append(button); return item;
  }));
  renderResultsTable();
}

function escapeHtml(value) { const div = document.createElement('div'); div.textContent = value; return div.innerHTML; }

function updateExamStats() {
  if (!state.current?.answers) return;
  let marked = 0, blank = 0, multiple = 0;
  let correct = 0, incorrect = 0, calculatedScore = 0;
  const key = state.answerKey || {};
  const hasKey = Object.keys(key).length > 0;

  for (const a of state.current.answers) {
    const q = a.question;
    const ansVal = (a.answer || '').trim().toUpperCase();
    const correctAns = (key[q] || '').trim().toUpperCase();

    if (a.state === 'multiple') multiple++;
    else if (a.state === 'blank') blank++;
    else marked++;

    if (hasKey && correctAns) {
      if (!ansVal || a.state === 'blank') {
        // En blanco: 0 puntos
      } else if ((a.state === 'ok' || a.state === 'manual') && ansVal === correctAns) {
        correct++;
        calculatedScore += 1.0;
      } else {
        incorrect++;
        calculatedScore -= 0.01;
      }
    }
  }

  const finalScore = state.current.score !== undefined ? state.current.score : calculatedScore;
  const finalCorrect = state.current.correct_count !== undefined ? state.current.correct_count : correct;
  const finalIncorrect = state.current.incorrect_count !== undefined ? state.current.incorrect_count : incorrect;

  const elScore = $('#stat-score-count');
  const elCorrect = $('#stat-correct-count');
  const elIncorrect = $('#stat-incorrect-count');
  const elMarked = $('#stat-marked-count');
  const elBlank = $('#stat-blank-count');
  const elMultiple = $('#stat-multiple-count');

  if (elScore) elScore.textContent = finalScore.toFixed(2);
  const scoreBox = document.querySelector('.stat-box.stat-score');
  if (scoreBox) {
    const hasEval = (state.current.score !== undefined && (state.current.status === 'approved' || state.current.score !== 0)) || hasKey;
    scoreBox.classList.toggle('score-low', hasEval && finalScore < 50);
    scoreBox.classList.toggle('score-high', hasEval && finalScore >= 50);
  }
  if (elCorrect) elCorrect.textContent = finalCorrect;
  if (elIncorrect) elIncorrect.textContent = finalIncorrect;
  if (elMarked) elMarked.textContent = marked;
  if (elBlank) elBlank.textContent = blank;
  if (elMultiple) elMultiple.textContent = multiple;

  const multBox = document.querySelector('.stat-box.stat-multiple');
  if (multBox) multBox.classList.toggle('has-alert', multiple > 0);
}

function updateApproveButton() {
  const btn = $('#approve');
  if (!btn || !state.current) return;
  const isApproved = state.current.status === 'approved';
  const isAssigned = Boolean((state.current.student || state.current.student_name || state.current.student_code || '').trim());

  if (isApproved) {
    btn.textContent = 'Aprobada';
    btn.disabled = true;
    btn.title = 'Esta hoja ya está aprobada.';
  } else if (!isAssigned) {
    btn.textContent = 'Aprobar hoja';
    btn.disabled = true;
    btn.title = 'Debe asignar un estudiante antes de poder aprobar este examen.';
  } else {
    btn.textContent = 'Aprobar hoja';
    btn.disabled = false;
    btn.title = 'Aprobar hoja y registrar calificación.';
  }
}

async function openSheet(id) {
  message('#viewer-status', 'Cargando hoja...');
  state.current = await request(`/api/sheets/${id}`);
  const position = state.batch.sheets.findIndex((sheet) => sheet.id === id) + 1;
  $('#sheet-index').textContent = `Hoja ${position} de ${state.batch.sheets.length}`;
  $('#sheet-title').textContent = state.current.source_name + (state.current.page_number ? ` · página ${state.current.page_number}` : '');
  $('#threshold').value = state.current.threshold;
  $('#threshold-value').textContent = state.current.threshold;
  updateApproveButton();
  updateExamStats();
  syncStudentCombobox();
  state.image = new Image();
  state.image.onload = () => { draw(); message('#viewer-status', 'Revise las marcas antes de aprobar.'); };
  state.image.src = `${state.current.image_url}?v=${Date.now()}`;
  renderBatch();
}

function draw() {
  if (!state.image) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.image, 0, 0, canvas.width, canvas.height);
  if (!state.grid || !state.current?.answers) return;
  for (const answer of state.current.answers) {
    if (answer.state === 'blank') continue;
    const isMultiple = answer.state === 'multiple';
    const color = answer.state === 'manual' ? '#147e54' : isMultiple ? '#c22b10' : answer.state === 'ok' ? '#1468c9' : '#c22b10';
    const letters = answer.answer || '';
    if (isMultiple && letters === 'DOBLE') {
      const scores = answer.scores || {};
      const sortedKeys = Object.keys(scores).sort((a, b) => scores[b] - scores[a]);
      for (const k of sortedKeys.slice(0, 2)) {
        const option = optionLetters.indexOf(k);
        if (option >= 0) {
          const point = calibratedPoint(answer.question, option);
          ctx.beginPath();
          ctx.arc(point.x, point.y, 6.5, 0, Math.PI * 2);
          ctx.lineWidth = 3;
          ctx.strokeStyle = color;
          ctx.stroke();
        }
      }
    } else {
      for (const ch of letters) {
        const option = optionLetters.indexOf(ch);
        if (option >= 0) {
          const point = calibratedPoint(answer.question, option);
          ctx.beginPath();
          ctx.arc(point.x, point.y, isMultiple ? 6.5 : 5.5, 0, Math.PI * 2);
          ctx.lineWidth = isMultiple ? 3 : 2.5;
          ctx.strokeStyle = color;
          ctx.stroke();
        }
      }
    }
  }
}

$('#threshold').addEventListener('input', () => { $('#threshold-value').textContent = $('#threshold').value; });
$('#reread').addEventListener('click', async () => {
  try {
    message('#viewer-status', 'Leyendo la hoja con el umbral seleccionado...');
    const sheet = await request(`/api/sheets/${state.current.id}/read`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ threshold: Number($('#threshold').value) }) });
    state.current = sheet;
    const target = state.batch.sheets.find((item) => item.id === sheet.id);
    Object.assign(target, sheet);
    updateExamStats();
    draw(); renderBatch();
    message('#viewer-status', 'Lectura actualizada. Revise las detecciones antes de aprobar.');
  } catch (error) { message('#viewer-status', error.message); }
});
$('#grid').addEventListener('click', () => { state.grid = !state.grid; $('#grid').textContent = state.grid ? 'Ocultar cuadrícula' : 'Mostrar cuadrícula'; draw(); });
$('#approve').addEventListener('click', async () => {
  const isAssigned = Boolean((state.current?.student || state.current?.student_name || state.current?.student_code || '').trim());
  if (!isAssigned) {
    alert('No se puede aprobar el examen: Debe asignar un estudiante a esta hoja primero.');
    message('#viewer-status', '⚠️ Debe asignar un estudiante antes de aprobar.');
    if (studentInput) {
      studentInput.focus();
      openStudentDropdown();
    }
    return;
  }
  try {
    state.current = await request(`/api/sheets/${state.current.id}/approve`, { method: 'POST' });
    const target = state.batch.sheets.find((sheet) => sheet.id === state.current.id);
    Object.assign(target, state.current);
    renderBatch();
    renderResultsTable();
    updateApproveButton();
    message('#viewer-status', 'Hoja aprobada. Puede continuar con la siguiente.');
  } catch (error) { message('#viewer-status', error.message); }
});
$('#export').addEventListener('click', () => { window.location.href = `/api/batches/${state.batch.id}/export.xlsx`; });
const exportDetailedBtn = $('#export-detailed');
if (exportDetailedBtn) {
  exportDetailedBtn.addEventListener('click', () => {
    if (!state.batch) return;
    window.location.href = `/api/batches/${state.batch.id}/export-detailed.xlsx`;
  });
}
const btnResultsExportDetailed = $('#btn-results-export-detailed');
if (btnResultsExportDetailed) {
  btnResultsExportDetailed.addEventListener('click', () => {
    if (!state.batch) return;
    window.location.href = `/api/batches/${state.batch.id}/export-detailed.xlsx`;
  });
}

// Botón para subir más exámenes
const btnUploadMore = $('#btn-upload-more');
const moreFilesInput = $('#more-files');
if (btnUploadMore && moreFilesInput) {
  btnUploadMore.addEventListener('click', () => {
    moreFilesInput.click();
  });

  moreFilesInput.addEventListener('change', async () => {
    const files = moreFilesInput.files;
    if (!files || files.length === 0) return;
    try {
      await uploadFilesPipeline(files, true);
    } catch (err) {
      alert('Error al subir más exámenes: ' + err.message);
      message('#viewer-status', err.message);
      const wsProgress = $('#workspace-upload-progress');
      if (wsProgress) wsProgress.hidden = true;
    } finally {
      moreFilesInput.value = '';
    }
  });
}

/* ==================== MODAL DE CORRECCIÓN MANUAL ==================== */
const modal = $('#modal-correction');

function openCorrectionModal() {
  if (!state.current || !state.current.answers) return;
  $('#modal-subtitle').textContent = `${state.current.source_name}${state.current.page_number ? ` · Página ${state.current.page_number}` : ''}`;
  renderModalQuestions();
  modal.hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeCorrectionModal() {
  modal.hidden = true;
  document.body.style.overflow = '';
}

function updateSelectStyle(select, origAnswer) {
  select.classList.remove('val-empty', 'val-selected', 'val-manual', 'val-multiple');
  const val = select.value;
  const badge = select.closest('.modal-question-row')?.querySelector('.modal-badge');
  if (!val) {
    select.classList.add('val-empty');
    if (badge) { badge.className = 'modal-badge badge-blank'; badge.textContent = 'Vacía'; }
  } else if (val === 'MULTIPLE') {
    select.classList.add('val-multiple');
    if (badge) { badge.className = 'modal-badge badge-multiple'; badge.textContent = 'Doble marca'; }
  } else if (val !== origAnswer) {
    select.classList.add('val-manual');
    if (badge) { badge.className = 'modal-badge badge-manual'; badge.textContent = 'Manual'; }
  } else {
    select.classList.add('val-selected');
    if (badge) {
      if (select.dataset.state === 'multiple') {
        badge.className = 'modal-badge badge-multiple'; badge.textContent = 'Doble marca';
      } else if (select.dataset.state === 'uncertain') {
        badge.className = 'modal-badge badge-review'; badge.textContent = 'Revisar';
      } else if (select.dataset.state === 'manual') {
        badge.className = 'modal-badge badge-manual'; badge.textContent = 'Manual';
      } else {
        badge.className = 'modal-badge badge-ok'; badge.textContent = 'OK';
      }
    }
  }
}

function updateModalStats() {
  const selects = modal.querySelectorAll('.modal-choice-select');
  let marked = 0, blank = 0, multiple = 0, manual = 0;
  selects.forEach((sel) => {
    const val = sel.value;
    const orig = sel.dataset.original;
    if (!val) {
      blank++;
    } else if (val === 'MULTIPLE') {
      multiple++;
    } else {
      marked++;
    }
    if (val !== orig || sel.dataset.state === 'manual') manual++;
  });
  $('#modal-stats').textContent = `${marked} marcadas · ${blank} vacías · ${multiple} doble marca ${manual > 0 ? `· ${manual} modificadas` : ''}`;
}

function renderModalQuestions() {
  const container = $('#modal-blocks-container');
  container.innerHTML = '';
  const answers = state.current.answers;

  for (let blockIdx = 0; blockIdx < 4; blockIdx++) {
    const startQ = blockIdx * 35 + 1;
    const endQ = startQ + 34;

    const blockDiv = document.createElement('div');
    blockDiv.className = 'modal-block';
    blockDiv.id = `block-${blockIdx + 1}`;

    const blockHeader = document.createElement('div');
    blockHeader.className = 'modal-block-header';
    blockHeader.innerHTML = `<span>Bloque ${blockIdx + 1}</span><span>${String(startQ).padStart(3, '0')} - ${String(endQ).padStart(3, '0')}</span>`;
    blockDiv.appendChild(blockHeader);

    for (let i = 0; i < 35; i++) {
      const qNum = startQ + i;
      const ans = answers.find((a) => a.question === qNum) || { question: qNum, answer: '', state: 'blank' };

      const row = document.createElement('div');
      row.className = 'modal-question-row';

      const numSpan = document.createElement('span');
      numSpan.className = 'modal-q-num';
      numSpan.textContent = String(qNum).padStart(3, '0');

      const select = document.createElement('select');
      select.className = 'modal-choice-select';
      select.dataset.question = qNum;
      select.dataset.original = ans.answer || '';
      select.dataset.state = ans.state || 'blank';

      const emptyOption = document.createElement('option');
      emptyOption.value = '';
      emptyOption.textContent = '— (Vacía)';
      select.appendChild(emptyOption);

      for (const letter of optionLetters) {
        const opt = document.createElement('option');
        opt.value = letter;
        opt.textContent = `Alternativa ${letter}`;
        select.appendChild(opt);
      }

      const multOpt = document.createElement('option');
      multOpt.value = 'MULTIPLE';
      multOpt.textContent = '⚠️ Doble marca';
      select.appendChild(multOpt);

      if (ans.state === 'multiple') {
        select.value = 'MULTIPLE';
      } else {
        select.value = ans.answer || '';
      }

      const badge = document.createElement('span');
      badge.className = 'modal-badge';
      if (ans.state === 'multiple') {
        badge.classList.add('badge-multiple'); badge.textContent = 'Doble marca';
      } else if (ans.state === 'manual') {
        badge.classList.add('badge-manual'); badge.textContent = 'Manual';
      } else if (ans.state === 'uncertain') {
        badge.classList.add('badge-review'); badge.textContent = 'Revisar';
      } else if (ans.state === 'ok') {
        badge.classList.add('badge-ok'); badge.textContent = 'OK';
      } else {
        badge.classList.add('badge-blank'); badge.textContent = 'Vacía';
      }

      updateSelectStyle(select, ans.answer || '');

      select.addEventListener('change', () => {
        updateSelectStyle(select, select.dataset.original);
        updateModalStats();
      });

      row.appendChild(numSpan);
      row.appendChild(select);
      row.appendChild(badge);
      blockDiv.appendChild(row);
    }

    container.appendChild(blockDiv);
  }

  updateModalStats();
}

// Botón para abrir modal
$('#btn-manual-correct').addEventListener('click', openCorrectionModal);

// Botones para cerrar modal
$('#modal-close').addEventListener('click', closeCorrectionModal);
$('#modal-cancel').addEventListener('click', closeCorrectionModal);

// Cerrar con Escape o clic fuera
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !modal.hidden) closeCorrectionModal();
});
modal.addEventListener('click', (e) => {
  if (e.target === modal) closeCorrectionModal();
});

// Navegación rápida por bloques dentro del modal
modal.querySelectorAll('[data-jump]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const jump = btn.dataset.jump;
    const targetBlock = jump === 'b1' ? '#block-1' : jump === 'b2' ? '#block-2' : jump === 'b3' ? '#block-3' : '#block-4';
    const el = modal.querySelector(targetBlock);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// Guardar / Actualizar respuestas
$('#modal-submit').addEventListener('click', async () => {
  if (!state.current) return;
  const submitBtn = $('#modal-submit');
  const originalText = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = 'Actualizando...';

  try {
    const selects = modal.querySelectorAll('.modal-choice-select');
    const newAnswers = [];

    selects.forEach((sel) => {
      const q = parseInt(sel.dataset.question, 10);
      const val = sel.value.trim().toUpperCase();
      const orig = sel.dataset.original.trim().toUpperCase();
      const origState = sel.dataset.state;
      let stateVal;
      let ansVal = val;
      if (!val) {
        stateVal = 'blank';
      } else if (val === 'MULTIPLE') {
        stateVal = 'multiple';
        ansVal = origState === 'multiple' && orig ? orig : 'DOBLE';
      } else if (val !== orig || origState === 'manual') {
        stateVal = 'manual';
      } else {
        stateVal = origState;
      }
      newAnswers.push({
        question: q,
        answer: ansVal,
        state: stateVal,
        confidence: 1.0,
      });
    });

    const updatedSheet = await request(`/api/sheets/${state.current.id}/answers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers: newAnswers }),
    });

    state.current = updatedSheet;
    const target = state.batch.sheets.find((item) => item.id === updatedSheet.id);
    if (target) Object.assign(target, updatedSheet);

    closeCorrectionModal();
    updateExamStats();
    draw();
    renderBatch();

    updateApproveButton();
    message('#viewer-status', 'Respuestas actualizadas correctamente. Ahora puede aprobar la hoja.');
  } catch (error) {
    alert('Error al actualizar las respuestas: ' + error.message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = originalText;
  }
});

/* ==================== GESTIÓN Y COMBOBOX DE ESTUDIANTES ==================== */
const studentInput = $('#student-combo-input');
const studentClearBtn = $('#student-combo-clear');
const studentToggleBtn = $('#student-combo-toggle');
const studentDropdown = $('#student-dropdown');
const studentOptionsList = $('#student-options-list');
const studentCountBadge = $('#student-count-badge');
const studentStatusTag = $('#student-status-tag');

async function loadStudents() {
  try {
    const res = await request('/api/students');
    state.students = res.students || [];
    if (studentCountBadge) {
      studentCountBadge.textContent = `${state.students.length} alumnos`;
    }
  } catch (err) {
    console.error('Error cargando lista de alumnos:', err);
  }
}

function syncStudentCombobox() {
  if (!studentInput) return;
  const currentStudent = state.current?.student || '';
  studentInput.value = currentStudent;
  
  if (currentStudent) {
    if (studentClearBtn) studentClearBtn.hidden = false;
    if (studentStatusTag) {
      studentStatusTag.textContent = '✓ Asignado';
      studentStatusTag.className = 'student-tag tag-assigned';
      studentStatusTag.title = currentStudent;
    }
  } else {
    if (studentClearBtn) studentClearBtn.hidden = true;
    if (studentStatusTag) {
      studentStatusTag.textContent = 'Sin asignar';
      studentStatusTag.className = 'student-tag tag-unassigned';
      studentStatusTag.title = 'Haga clic para asignar estudiante';
    }
  }
  updateApproveButton();
}

function normalizeSearch(str) {
  return (str || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim();
}

function filterStudents(query = '') {
  const q = normalizeSearch(query);
  if (!q) {
    state.filteredStudents = state.students.slice();
  } else {
    state.filteredStudents = state.students.filter((s) => {
      const codeMatch = normalizeSearch(s.code).includes(q);
      const nameMatch = normalizeSearch(s.name).includes(q);
      const labelMatch = normalizeSearch(s.label).includes(q);
      return codeMatch || nameMatch || labelMatch;
    });
  }
  renderStudentDropdownOptions();
}

function getAssignedToOtherInfo(studentOrData) {
  if (!state.batch?.sheets || !studentOrData) return null;
  const targetCode = (studentOrData.code || '').trim().toLowerCase();
  const targetName = (studentOrData.name || '').trim().toLowerCase();
  const targetLabel = (studentOrData.label || studentOrData.student || '').trim().toLowerCase();

  for (let i = 0; i < state.batch.sheets.length; i++) {
    const sheet = state.batch.sheets[i];
    if (sheet.id === state.current?.id) continue;
    const otherCode = (sheet.student_code || '').trim().toLowerCase();
    const otherName = (sheet.student_name || '').trim().toLowerCase();
    const otherLabel = (sheet.student || `${sheet.student_code || ''} - ${sheet.student_name || ''}`).trim().toLowerCase();

    if (targetCode && otherCode && targetCode === otherCode) {
      return {
        sheetIndex: i + 1,
        sourceName: sheet.source_name,
        display: sheet.student || `${sheet.student_code} - ${sheet.student_name}`.trim()
      };
    }
    if (targetName && otherName && targetName === otherName) {
      return {
        sheetIndex: i + 1,
        sourceName: sheet.source_name,
        display: sheet.student || sheet.student_name
      };
    }
    if (targetLabel && otherLabel && targetLabel === otherLabel) {
      return {
        sheetIndex: i + 1,
        sourceName: sheet.source_name,
        display: sheet.student
      };
    }
  }
  return null;
}

function renderStudentDropdownOptions() {
  if (!studentOptionsList) return;
  studentOptionsList.innerHTML = '';
  state.highlightedStudentIndex = -1;

  if (state.filteredStudents.length === 0) {
    const noMatch = document.createElement('div');
    noMatch.className = 'student-no-match';
    const query = studentInput ? studentInput.value.trim() : '';
    noMatch.innerHTML = query 
      ? `<span>No se encontró "<strong>${escapeHtml(query)}</strong>".<br><small>Pulse Enter para asignarlo directamente.</small></span>`
      : '<span>No hay alumnos en el padrón.</span>';
    studentOptionsList.appendChild(noMatch);
    return;
  }

  const currentStudentLabel = (state.current?.student || '').trim().toLowerCase();

  state.filteredStudents.forEach((student, index) => {
    const item = document.createElement('div');
    item.className = 'student-option-item';
    item.setAttribute('role', 'option');
    item.dataset.index = index;

    const isSelected = student.label.toLowerCase() === currentStudentLabel || 
      (state.current?.student_code && state.current.student_code.toLowerCase() === student.code.toLowerCase());
    if (isSelected) {
      item.classList.add('selected');
    }

    const assignedOther = getAssignedToOtherInfo(student);
    if (assignedOther) {
      item.classList.add('disabled-assigned');
      item.title = `Ya asignado a la Hoja ${assignedOther.sheetIndex} (${assignedOther.sourceName})`;
    }

    item.innerHTML = `
      ${student.code ? `<span class="student-code-badge">${escapeHtml(student.code)}</span>` : ''}
      <span class="student-name-text">${escapeHtml(student.name || student.label)}</span>
      ${assignedOther ? `<span class="student-assigned-badge" title="Ya asignado en Hoja ${assignedOther.sheetIndex}">🔒 Hoja ${assignedOther.sheetIndex}</span>` : ''}
    `;

    item.addEventListener('click', () => {
      if (assignedOther) {
        alert(`No se puede asignar: El estudiante "${student.label || student.name}" ya está asignado a la Hoja ${assignedOther.sheetIndex} (${assignedOther.sourceName}).\n\nNo se permite asignar el mismo estudiante a dos exámenes.`);
        return;
      }
      selectStudent(student);
    });

    item.addEventListener('mouseenter', () => {
      highlightStudentIndex(index);
    });

    studentOptionsList.appendChild(item);
  });
}

function highlightStudentIndex(index) {
  if (!studentOptionsList) return;
  const items = studentOptionsList.querySelectorAll('.student-option-item');
  items.forEach((it) => it.classList.remove('highlighted'));
  if (index >= 0 && index < items.length) {
    state.highlightedStudentIndex = index;
    items[index].classList.add('highlighted');
    items[index].scrollIntoView({ block: 'nearest' });
  } else {
    state.highlightedStudentIndex = -1;
  }
}

function openStudentDropdown() {
  if (!studentDropdown || !studentInput) return;
  filterStudents(studentInput.value);
  studentDropdown.hidden = false;
  studentInput.setAttribute('aria-expanded', 'true');
}

function closeStudentDropdown() {
  if (!studentDropdown || !studentInput) return;
  studentDropdown.hidden = true;
  studentInput.setAttribute('aria-expanded', 'false');
  state.highlightedStudentIndex = -1;
}

async function selectStudent(student) {
  if (studentInput) studentInput.value = student.label;
  await assignStudentToCurrentSheet(student.code, student.name, student.label);
  closeStudentDropdown();
}

async function assignStudentToCurrentSheet(studentCode, studentName, studentLabel) {
  if (!state.current) return;
  const sCode = (studentCode || '').trim();
  const sName = (studentName || '').trim();
  const sLabel = (studentLabel || '').trim();

  // Validación de no duplicidad en el lote
  if (sCode || sName || sLabel) {
    let parsedCode = sCode;
    let parsedName = sName;
    if (!parsedCode && !parsedName && sLabel) {
      if (sLabel.includes(' - ')) {
        const parts = sLabel.split(' - ');
        parsedCode = parts[0].trim();
        parsedName = parts[1].trim();
      } else if (sLabel.includes(',')) {
        const parts = sLabel.split(',');
        parsedCode = parts[0].trim();
        parsedName = parts[1].trim();
      }
    }

    const other = getAssignedToOtherInfo({ code: parsedCode, name: parsedName, label: sLabel });
    if (other) {
      alert(`No se puede asignar: El estudiante "${sLabel || parsedName || parsedCode}" ya está asignado a la Hoja ${other.sheetIndex} (${other.sourceName}).\n\nNo se permite asignar un mismo estudiante a dos exámenes.`);
      syncStudentCombobox();
      return;
    }
  }

  try {
    message('#viewer-status', 'Asignando estudiante al examen...');
    const res = await request(`/api/sheets/${state.current.id}/student`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        code: sCode, 
        name: sName, 
        student: sLabel 
      }),
    });

    state.current.student_code = res.student_code;
    state.current.student_name = res.student_name;
    state.current.student = res.student;
    if (res.status) state.current.status = res.status;

    const target = state.batch?.sheets?.find((s) => s.id === state.current.id);
    if (target) {
      target.student_code = res.student_code;
      target.student_name = res.student_name;
      target.student = res.student;
      if (res.status) target.status = res.status;
    }

    syncStudentCombobox();
    renderBatch();
    renderResultsTable();
    message('#viewer-status', res.student ? `Estudiante asignado: ${res.student}` : 'Asignación de estudiante quitada.');
  } catch (err) {
    alert(err.message);
    syncStudentCombobox();
    message('#viewer-status', err.message);
  }
}

if (studentInput) {
  studentInput.addEventListener('focus', () => {
    openStudentDropdown();
  });

  studentInput.addEventListener('input', () => {
    openStudentDropdown();
    filterStudents(studentInput.value);
  });

  studentInput.addEventListener('keydown', async (e) => {
    if (studentDropdown.hidden) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        openStudentDropdown();
        e.preventDefault();
        return;
      }
    }

    const items = studentOptionsList ? studentOptionsList.querySelectorAll('.student-option-item') : [];
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const nextIdx = state.highlightedStudentIndex < items.length - 1 ? state.highlightedStudentIndex + 1 : 0;
      highlightStudentIndex(nextIdx);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prevIdx = state.highlightedStudentIndex > 0 ? state.highlightedStudentIndex - 1 : items.length - 1;
      highlightStudentIndex(prevIdx);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (state.highlightedStudentIndex >= 0 && state.filteredStudents[state.highlightedStudentIndex]) {
        const student = state.filteredStudents[state.highlightedStudentIndex];
        const assignedOther = getAssignedToOtherInfo(student);
        if (assignedOther) {
          alert(`No se puede asignar: El estudiante "${student.label || student.name}" ya está asignado a la Hoja ${assignedOther.sheetIndex} (${assignedOther.sourceName}).\n\nNo se permite asignar el mismo estudiante a dos exámenes.`);
          return;
        }
        selectStudent(student);
      } else {
        const val = studentInput.value.trim();
        await assignStudentToCurrentSheet('', '', val);
        closeStudentDropdown();
      }
    } else if (e.key === 'Escape') {
      closeStudentDropdown();
    }
  });

  studentInput.addEventListener('blur', (e) => {
    setTimeout(() => {
      if (!studentDropdown.contains(document.activeElement) && document.activeElement !== studentToggleBtn) {
        closeStudentDropdown();
        const typed = studentInput.value.trim();
        if (state.current && typed !== (state.current.student || '')) {
          assignStudentToCurrentSheet('', '', typed);
        }
      }
    }, 200);
  });
}

if (studentToggleBtn) {
  studentToggleBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (studentDropdown.hidden) {
      studentInput.focus();
      openStudentDropdown();
    } else {
      closeStudentDropdown();
    }
  });
}

if (studentClearBtn) {
  studentClearBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    studentInput.value = '';
    await assignStudentToCurrentSheet('', '', '');
    closeStudentDropdown();
    studentInput.focus();
  });
}

// Cerrar dropdown al hacer clic fuera
document.addEventListener('click', (e) => {
  const container = $('#student-combobox-wrap');
  if (container && !container.contains(e.target) && studentDropdown && !studentDropdown.hidden) {
    closeStudentDropdown();
  }
});

/* Modal de Gestión de Padrón de Alumnos */
const modalStudents = $('#modal-students');
const btnManageStudents = $('#btn-manage-students');
const btnCloseStudents = $('#modal-students-close');
const btnCancelStudents = $('#modal-students-cancel');
const btnSaveStudents = $('#modal-students-save');
const studentsTextarea = $('#students-textarea');
const studentsSaveStatus = $('#students-save-status');

if (btnManageStudents) {
  btnManageStudents.addEventListener('click', async () => {
    await loadStudents();
    if (studentsTextarea) {
      studentsTextarea.value = state.students.map((s) => s.label).join('\n');
    }
    if (studentsSaveStatus) studentsSaveStatus.textContent = '';
    modalStudents.hidden = false;
    document.body.style.overflow = 'hidden';
  });
}

function closeStudentsModal() {
  if (modalStudents) modalStudents.hidden = true;
  document.body.style.overflow = '';
}

if (btnCloseStudents) btnCloseStudents.addEventListener('click', closeStudentsModal);
if (btnCancelStudents) btnCancelStudents.addEventListener('click', closeStudentsModal);

if (btnSaveStudents) {
  btnSaveStudents.addEventListener('click', async () => {
    btnSaveStudents.disabled = true;
    btnSaveStudents.textContent = 'Guardando...';
    try {
      const text = studentsTextarea.value;
      const res = await request('/api/students', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ students_text: text }),
      });
      state.students = res.students || [];
      if (studentCountBadge) {
        studentCountBadge.textContent = `${state.students.length} alumnos`;
      }
      closeStudentsModal();
      message('#viewer-status', `Padrón actualizado: ${state.students.length} alumnos registrados.`);
    } catch (err) {
      alert('Error al guardar el padrón: ' + err.message);
    } finally {
      btnSaveStudents.disabled = false;
      btnSaveStudents.textContent = 'Guardar padrón';
    }
  });
}

/* ==================== CLAVE OFICIAL DE RESPUESTAS (140 PREGUNTAS) ==================== */
const modalAnswerKey = $('#modal-answer-key');
const btnOpenAnswerKey = $('#btn-open-answer-key');
const btnWorkspaceKey = $('#btn-workspace-key');
const btnCloseAnswerKey = $('#modal-key-close');
const btnCancelAnswerKey = $('#modal-key-cancel');
const btnSaveAnswerKey = $('#modal-key-save');
const keySummaryBadge = $('#key-summary-badge');
const startKeyBanner = $('#start-key-banner');
const startKeyStatusText = $('#start-key-status-text');
const keyBlocksContainer = $('#key-blocks-container');

// Fast paste tools
const btnKeyTogglePaste = $('#btn-key-toggle-paste');
const btnKeyApplyPaste = $('#btn-key-apply-paste');
const btnKeyCancelPaste = $('#btn-key-cancel-paste');
const keyPasteBox = $('#key-paste-box');
const keyPasteInput = $('#key-paste-input');
const btnKeySample = $('#btn-key-sample');
const btnKeyClear = $('#btn-key-clear');

let modalKeyDraft = {};

async function loadAnswerKey() {
  try {
    const res = await request('/api/answer-key');
    state.answerKey = res.key || {};
    updateStartKeyBanner();
  } catch (err) {
    console.error('Error cargando clave de respuestas:', err);
  }
}

function updateStartKeyBanner() {
  const count = Object.keys(state.answerKey || {}).filter((k) => state.answerKey[k]).length;
  if (startKeyBanner && startKeyStatusText) {
    if (count > 0) {
      startKeyBanner.className = 'key-status-banner has-key';
      startKeyStatusText.innerHTML = `✓ Clave oficial configurada (<strong>${count} de 140</strong> preguntas registradas).`;
    } else {
      startKeyBanner.className = 'key-status-banner';
      startKeyStatusText.innerHTML = `⚠️ Clave oficial sin configurar. Configure la clave para calificar los exámenes.`;
    }
  }
}

function updateModalKeyCountBadge() {
  if (!keySummaryBadge) return;
  const count = Object.keys(modalKeyDraft).filter((k) => modalKeyDraft[k]).length;
  keySummaryBadge.textContent = `${count} / 140 configuradas`;
}

function renderKeyModalGrid() {
  if (!keyBlocksContainer) return;
  keyBlocksContainer.innerHTML = '';
  modalKeyDraft = { ...state.answerKey };

  for (let blockIdx = 0; blockIdx < 4; blockIdx++) {
    const startQ = blockIdx * 35 + 1;
    const endQ = startQ + 34;

    const blockDiv = document.createElement('div');
    blockDiv.className = 'key-block';
    blockDiv.id = `kblock-${blockIdx + 1}`;

    const blockHeader = document.createElement('div');
    blockHeader.className = 'key-block-header';
    blockHeader.innerHTML = `<span>Bloque ${blockIdx + 1}</span><span>${String(startQ).padStart(3, '0')} - ${String(endQ).padStart(3, '0')}</span>`;
    blockDiv.appendChild(blockHeader);

    for (let i = 0; i < 35; i++) {
      const qNum = startQ + i;
      const currentAns = modalKeyDraft[qNum] || '';

      const row = document.createElement('div');
      row.className = 'key-question-row';

      const numSpan = document.createElement('span');
      numSpan.className = 'key-q-num';
      numSpan.textContent = String(qNum).padStart(3, '0');

      const optionsGroup = document.createElement('div');
      optionsGroup.className = 'key-options-group';

      for (const letter of optionLetters) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `key-opt-btn ${currentAns === letter ? 'active' : ''}`;
        btn.textContent = letter;
        btn.dataset.question = qNum;
        btn.dataset.option = letter;

        btn.addEventListener('click', () => {
          if (modalKeyDraft[qNum] === letter) {
            delete modalKeyDraft[qNum];
            btn.classList.remove('active');
          } else {
            modalKeyDraft[qNum] = letter;
            optionsGroup.querySelectorAll('.key-opt-btn').forEach((b) => b.classList.remove('active'));
            btn.classList.add('active');
          }
          updateModalKeyCountBadge();
        });

        optionsGroup.appendChild(btn);
      }

      const clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.className = 'key-opt-clear';
      clearBtn.title = 'Limpiar esta pregunta';
      clearBtn.innerHTML = '&times;';
      clearBtn.addEventListener('click', () => {
        delete modalKeyDraft[qNum];
        optionsGroup.querySelectorAll('.key-opt-btn').forEach((b) => b.classList.remove('active'));
        updateModalKeyCountBadge();
      });
      optionsGroup.appendChild(clearBtn);

      row.appendChild(numSpan);
      row.appendChild(optionsGroup);
      blockDiv.appendChild(row);
    }

    keyBlocksContainer.appendChild(blockDiv);
  }

  updateModalKeyCountBadge();
}

function openAnswerKeyModal() {
  renderKeyModalGrid();
  if (keyPasteBox) keyPasteBox.hidden = true;
  if (modalAnswerKey) modalAnswerKey.hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeAnswerKeyModal() {
  if (modalAnswerKey) modalAnswerKey.hidden = true;
  document.body.style.overflow = '';
}

if (btnOpenAnswerKey) btnOpenAnswerKey.addEventListener('click', openAnswerKeyModal);
if (btnWorkspaceKey) btnWorkspaceKey.addEventListener('click', openAnswerKeyModal);
if (btnCloseAnswerKey) btnCloseAnswerKey.addEventListener('click', closeAnswerKeyModal);
if (btnCancelAnswerKey) btnCancelAnswerKey.addEventListener('click', closeAnswerKeyModal);

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modalAnswerKey && !modalAnswerKey.hidden) closeAnswerKeyModal();
});
if (modalAnswerKey) {
  modalAnswerKey.addEventListener('click', (e) => {
    if (e.target === modalAnswerKey) closeAnswerKeyModal();
  });
}

if (modalAnswerKey) {
  modalAnswerKey.querySelectorAll('[data-key-jump]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const jump = btn.dataset.keyJump;
      const targetId = jump === 'kb1' ? '#kblock-1' : jump === 'kb2' ? '#kblock-2' : jump === 'kb3' ? '#kblock-3' : '#kblock-4';
      const el = modalAnswerKey.querySelector(targetId);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

if (btnKeySample) {
  btnKeySample.addEventListener('click', () => {
    for (let q = 1; q <= 140; q++) {
      modalKeyDraft[q] = optionLetters[(q - 1) % 5];
    }
    keyBlocksContainer.querySelectorAll('.key-question-row').forEach((row) => {
      const qNum = parseInt(row.querySelector('.key-q-num').textContent, 10);
      const chosen = modalKeyDraft[qNum];
      row.querySelectorAll('.key-opt-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.option === chosen);
      });
    });
    updateModalKeyCountBadge();
  });
}

if (btnKeyClear) {
  btnKeyClear.addEventListener('click', () => {
    if (!confirm('¿Desea borrar todas las respuestas de la clave?')) return;
    modalKeyDraft = {};
    keyBlocksContainer.querySelectorAll('.key-opt-btn').forEach((btn) => btn.classList.remove('active'));
    updateModalKeyCountBadge();
  });
}

if (btnKeyTogglePaste) {
  btnKeyTogglePaste.addEventListener('click', () => {
    if (keyPasteBox) {
      keyPasteBox.hidden = !keyPasteBox.hidden;
      if (!keyPasteBox.hidden && keyPasteInput) keyPasteInput.focus();
    }
  });
}
if (btnKeyCancelPaste) {
  btnKeyCancelPaste.addEventListener('click', () => {
    if (keyPasteBox) keyPasteBox.hidden = true;
  });
}
if (btnKeyApplyPaste) {
  btnKeyApplyPaste.addEventListener('click', () => {
    const text = keyPasteInput ? keyPasteInput.value : '';
    if (!text.trim()) return;
    const tokens = text.replace(/[,;\t\r\n]/g, ' ').split(/\s+/).filter(Boolean);
    let idx = 1;
    for (const token of tokens) {
      const clean = token.toUpperCase().trim();
      let matched = false;
      for (const sep of [':', '-', '.']) {
        if (clean.includes(sep)) {
          const parts = clean.split(sep);
          const q = parseInt(parts[0], 10);
          const ans = parts[1]?.trim();
          if (q >= 1 && q <= 140 && optionLetters.includes(ans)) {
            modalKeyDraft[q] = ans;
            matched = true;
          }
          break;
        }
      }
      if (!matched) {
        if (clean.length === 1 && optionLetters.includes(clean)) {
          if (idx <= 140) {
            modalKeyDraft[idx] = clean;
            idx++;
          }
        } else if (/^[ABCDE]+$/.test(clean)) {
          for (const ch of clean) {
            if (idx <= 140) {
              modalKeyDraft[idx] = ch;
              idx++;
            }
          }
        }
      }
    }

    keyBlocksContainer.querySelectorAll('.key-question-row').forEach((row) => {
      const qNum = parseInt(row.querySelector('.key-q-num').textContent, 10);
      const chosen = modalKeyDraft[qNum];
      row.querySelectorAll('.key-opt-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.option === chosen);
      });
    });
    updateModalKeyCountBadge();
    if (keyPasteBox) keyPasteBox.hidden = true;
  });
}

if (btnSaveAnswerKey) {
  btnSaveAnswerKey.addEventListener('click', async () => {
    btnSaveAnswerKey.disabled = true;
    btnSaveAnswerKey.textContent = 'Guardando...';

    try {
      const res = await request('/api/answer-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: modalKeyDraft }),
      });

      state.answerKey = res.key || {};
      updateStartKeyBanner();

      if (state.batch) {
        const batchData = await request(`/api/batches/${state.batch.id}`);
        state.batch.sheets = batchData.sheets;
        if (state.current) {
          const updatedCurrent = state.batch.sheets.find((s) => s.id === state.current.id);
          if (updatedCurrent) state.current = await request(`/api/sheets/${updatedCurrent.id}`);
          updateExamStats();
          updateApproveButton();
        }
        renderBatch();
      }

      closeAnswerKeyModal();
      message('#viewer-status', `Clave guardada (${res.count} respuestas). Los exámenes están en revisión.`);
    } catch (err) {
      alert('Error al guardar la clave: ' + err.message);
    } finally {
      btnSaveAnswerKey.disabled = false;
      btnSaveAnswerKey.textContent = 'Guardar clave';
    }
  });
}

// Inicializar lista de alumnos y clave al cargar la app
loadStudents();
loadAnswerKey();

/* ==================== TABLA DE RESULTADOS ==================== */
const resultsPanel = $('#results-panel');
const resultsTbody = $('#results-tbody');
const resultsCount = $('#results-count');

async function renderResultsTable() {
  if (!state.batch || !resultsPanel || !resultsTbody) return;

  const approved = state.batch.sheets.filter((s) => s.status === 'approved');
  if (approved.length === 0) {
    resultsPanel.hidden = true;
    return;
  }

  resultsPanel.hidden = false;
  if (resultsCount) {
    resultsCount.textContent = `${approved.length} aprobado${approved.length !== 1 ? 's' : ''}`;
  }
  const resultsExportDetailedBtn = $('#btn-results-export-detailed');
  if (resultsExportDetailedBtn) {
    resultsExportDetailedBtn.disabled = approved.length === 0;
  }

  resultsTbody.innerHTML = '';
  approved.forEach((sheet, idx) => {
    const tr = document.createElement('tr');
    const studentDisplay = sheet.student || '';
    const score = (sheet.score !== undefined ? sheet.score : 0).toFixed(2);

    tr.innerHTML = `
      <td class="cell-num">${idx + 1}</td>
      <td class="cell-code">${escapeHtml(sheet.student_code || '—')}</td>
      <td class="cell-name">${escapeHtml(sheet.student_name || studentDisplay || '—')}</td>
      <td class="cell-correct">${sheet.correct_count || 0}</td>
      <td class="cell-incorrect">${sheet.incorrect_count || 0}</td>
      <td class="cell-blank">${sheet.blank_count || 0}</td>
      <td class="cell-score">
        <span class="score-pill ${parseFloat(score) >= 50 ? 'score-high' : 'score-low'}">${score} pts</span>
      </td>
    `;
    resultsTbody.appendChild(tr);
  });
}
