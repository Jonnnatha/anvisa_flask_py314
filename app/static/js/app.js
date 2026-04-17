const form = document.getElementById('consulta-form');
const feedback = document.getElementById('feedback');
const resultado = document.getElementById('resultado');
const REQUEST_TIMEOUT_MS = 30000;

const materialTypeLabels = {
  pdf: 'PDF',
  manual: 'Manual',
  ifu: 'IFU / Instruções de uso',
  service_manual: 'Manual de serviço',
  training: 'Treinamento',
  complaint: 'Reclamação',
  forum: 'Fórum',
  catalog: 'Catálogo técnico',
  recall: 'Recall',
  safety_notice: 'Safety notice',
  field_corrective_action: 'Field corrective action',
  technical_bulletin: 'Boletim técnico',
  manufacturer_document: 'Documento do fabricante',
  technical_document: 'Documento técnico',
  public_signal: 'Sinal público',
  possible_material: 'Material plausível',
};

function materialBadge(item) {
  const typeLabel = materialTypeLabels[item.tipo] || item.tipo || 'Material';
  if (item.is_pdf && item.tipo === 'manual') return 'Manual PDF';
  if (item.is_pdf && item.tipo === 'ifu') return 'IFU PDF';
  if (item.is_pdf && item.tipo === 'service_manual') return 'Service Manual PDF';
  if (item.is_pdf) return 'PDF';
  return typeLabel;
}

function setFeedback(message, type = 'ok') {
  feedback.textContent = message;
  feedback.className = `feedback ${type}`;
  feedback.classList.remove('hidden');
}

function hideFeedback() {
  feedback.className = 'feedback hidden';
  feedback.textContent = '';
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function field(label, value) {
  if (value === undefined || value === null || String(value).trim() === '') {
    return '';
  }
  return `<div class="field"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function listField(label, values) {
  if (!Array.isArray(values) || !values.length) return '';
  const clean = values.filter(item => String(item || '').trim());
  if (!clean.length) return '';
  return `<div class="field"><span>${escapeHtml(label)}</span><strong>${escapeHtml(clean.join(' · '))}</strong></div>`;
}

function renderAlertLinks(alerts) {
  const validAlerts = alerts.filter(item => String(item?.numero_alerta || '').trim());
  if (!validAlerts.length) {
    return '<p>Nenhum alerta encontrado para este registro.</p>';
  }

  const chips = validAlerts.map((item) => {
    const number = String(item.numero_alerta).trim();
    const link = String(item.link_consulta || '').trim();
    if (!link) {
      return `<span class="alert-chip">${escapeHtml(number)}</span>`;
    }
    return `
      <a
        class="alert-chip alert-chip-link"
        href="${escapeHtml(link)}"
        target="_blank"
        rel="noopener noreferrer"
        title="Consultar alerta ${escapeHtml(number)}"
      >
        ${escapeHtml(number)}
      </a>
    `;
  }).join('');

  return `<div class="alerts-chip-list">${chips}</div>`;
}

function renderMaterial(item) {
  const tipo = materialBadge(item);
  const fonte = item.fonte || 'Fonte pública';
  const resumo = String(item.resumo || '').trim();
  const badgeClass = item.is_pdf ? 'material-badge is-pdf' : 'material-badge';
  const itemClass = item.is_pdf ? 'alert-item alert-item-partial material-item pdf-priority' : 'alert-item alert-item-partial material-item';

  return `
    <article class="${itemClass}">
      <h4>${escapeHtml(item.titulo || 'Documento técnico')}</h4>
      <div class="meta">
        <span class="${badgeClass}">${escapeHtml(tipo)}</span>
        <span>Fonte: ${escapeHtml(fonte)} · Confiança: ${escapeHtml(item.nivel_confianca || 'medio')}</span>
      </div>
      ${resumo ? `<p>${escapeHtml(resumo)}</p>` : ''}
      <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">Abrir material</a>
    </article>
  `;
}

function renderRecommendedSearches(searches) {
  const valid = Array.isArray(searches) ? searches.filter(item => item?.url && item?.query) : [];
  if (!valid.length) return '';
  const links = valid.map((item) => `
    <li>
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
        ${escapeHtml(item.query)}
      </a>
    </li>
  `).join('');
  return `
    <div class="recommended-searches">
      <h4>Pesquisas recomendadas</h4>
      <p>Use as consultas abaixo para investigar o produto manualmente.</p>
      <ul>${links}</ul>
    </div>
  `;
}

function renderGeneratedQueries(diagnostics) {
  const generated = Array.isArray(diagnostics?.generated_queries) ? diagnostics.generated_queries : [];
  if (!generated.length) return '';
  const items = generated.map((query) => `<li><code>${escapeHtml(query)}</code></li>`).join('');
  return `
    <div class="recommended-searches">
      <h4>Consultas geradas automaticamente</h4>
      <p>Consultas adaptativas criadas com base no contexto do produto.</p>
      <ul>${items}</ul>
    </div>
  `;
}

function renderDiagnosticsSummary(diagnostics) {
  if (!diagnostics || typeof diagnostics !== 'object') return '';
  const rows = [
    ['Status da busca', diagnostics.search_status],
    ['Consultas usadas', Array.isArray(diagnostics.queries_used) ? diagnostics.queries_used.length : undefined],
    ['Fontes consultadas', Array.isArray(diagnostics.sources_checked) ? diagnostics.sources_checked.join(' · ') : undefined],
    ['Resultados brutos', diagnostics.raw_results_count],
    ['Resultados aceitos', diagnostics.accepted_results_count],
    ['Resultados descartados', diagnostics.discarded_results_count],
  ]
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
    .map(([label, value]) => `<li><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</li>`)
    .join('');

  if (!rows) return '';
  return `
    <div class="recommended-searches">
      <h4>Diagnóstico da busca automática</h4>
      <ul>${rows}</ul>
    </div>
  `;
}

function renderDiagnosticsErrors(diagnostics) {
  const errors = Array.isArray(diagnostics?.errors) ? diagnostics.errors : [];
  if (!errors.length) return '';
  const items = errors.map((error) => {
    const source = error.source ? ` · Fonte: ${error.source}` : '';
    const strategy = error.strategy ? ` · Estratégia: ${error.strategy}` : '';
    return `<li><strong>${escapeHtml(error.type || 'erro')}</strong>: ${escapeHtml(error.message || 'Falha não detalhada.')}${escapeHtml(source)}${escapeHtml(strategy)}</li>`;
  }).join('');
  return `
    <div class="recommended-searches">
      <h4>Erros identificados na pesquisa</h4>
      <ul>${items}</ul>
    </div>
  `;
}

function render(data) {
  const productData = data.product_data || {};
  const labels = productData.labels || {};
  const fieldsOrder = productData.fields_order || [];
  const payload = productData.data || {};
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];
  const materials = Array.isArray(data.materials_or_signals) ? data.materials_or_signals : [];
  const materialsStatus = String(data.materials_status || '').trim();
  const materialsWarning = String(data.materials_warning || '').trim();
  const recommendedSearches = Array.isArray(data.materials_recommended_searches)
    ? data.materials_recommended_searches
    : [];
  const diagnostics = data.materials_diagnostics || {};

  const productFields = fieldsOrder.map((key) => {
    if (Array.isArray(payload[key])) {
      return listField(labels[key] || key, payload[key]);
    }
    return field(labels[key] || key, payload[key]);
  }).filter(Boolean).join('');

  const alertsHtml = renderAlertLinks(alerts);

  const fallbackByStatus = {
    no_results: 'Nenhum material técnico público relevante foi encontrado para este produto.',
    timeout: 'A busca falhou por timeout nesta consulta.',
    blocked: 'A busca automática foi bloqueada por uma fonte externa nesta consulta.',
    parse_failed: 'A coleta recebeu resposta, mas falhou ao interpretar os resultados.',
    collection_failed: 'A busca automática não conseguiu coletar resultados estruturados das fontes.',
    unexpected_error: 'Não foi possível concluir a busca por erro inesperado.',
    error: 'Não foi possível concluir a busca por erro inesperado.',
    partial_success: 'A busca foi encerrada antes de concluir totalmente, mas alguns materiais úteis foram encontrados.',
    success: '',
  };

  const statusMessage = fallbackByStatus[materialsStatus] || '';
  const primaryMessage = materialsWarning || statusMessage;
  const showRecommended = !materials.length || materials.length < 3;
  const recommendedHtml = showRecommended ? renderRecommendedSearches(recommendedSearches) : '';
  const generatedQueriesHtml = renderGeneratedQueries(diagnostics);
  const diagnosticsSummaryHtml = renderDiagnosticsSummary(diagnostics);
  const diagnosticsErrorsHtml = renderDiagnosticsErrors(diagnostics);
  const materialsHtml = materials.length
    ? `${primaryMessage ? `<p>${escapeHtml(primaryMessage)}</p>` : ''}${materials.map(renderMaterial).join('')}${diagnosticsErrorsHtml}${recommendedHtml}${generatedQueriesHtml}${diagnosticsSummaryHtml}`
    : `<p>${escapeHtml(primaryMessage || 'Não foi possível concluir a busca automática de materiais nesta consulta.')}</p>${diagnosticsErrorsHtml}${recommendedHtml}${generatedQueriesHtml}${diagnosticsSummaryHtml}`;

  resultado.innerHTML = `
    <div class="box">
      <h2>Dados do produto</h2>
      <div class="grid">${productFields || '<p>Sem campos confiáveis para exibir.</p>'}</div>
    </div>

    <div class="box">
      <h2>Alertas (${alerts.length})</h2>
      ${alertsHtml}
    </div>

    <div class="box">
      <h2>Materiais / sinais públicos úteis (${materials.length})</h2>
      ${materialsHtml}
    </div>
  `;

  resultado.classList.remove('hidden');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  hideFeedback();
  resultado.classList.add('hidden');
  const submitButton = form.querySelector('button[type="submit"]');
  const registro = document.getElementById('registro').value.replace(/\D/g, '');

  if (registro.length !== 11) {
    setFeedback('O registro ANVISA deve conter exatamente 11 dígitos.', 'error');
    return;
  }

  setFeedback('Consultando dados do produto, alertas e materiais técnicos...', 'ok');
  if (submitButton) submitButton.disabled = true;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`/api/consultar?registro=${encodeURIComponent(registro)}`, {
      signal: controller.signal,
    });
    const data = await response.json();

    if (!response.ok && data.error) {
      setFeedback(data.error, 'error');
      return;
    }

    if (!data.found) {
      setFeedback(data.message || 'Registro não encontrado.', 'error');
      return;
    }

    setFeedback(data.message || 'Consulta realizada com sucesso.', 'ok');
    render(data);
  } catch (err) {
    if (err?.name === 'AbortError') {
      setFeedback('A consulta excedeu o tempo limite. Tente novamente em instantes.', 'error');
    } else {
      setFeedback('Falha ao consultar o sistema. Tente novamente.', 'error');
    }
  } finally {
    window.clearTimeout(timeoutId);
    if (submitButton) submitButton.disabled = false;
  }
});
