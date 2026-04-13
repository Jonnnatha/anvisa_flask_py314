const form = document.getElementById('consulta-form');
const feedback = document.getElementById('feedback');
const resultado = document.getElementById('resultado');

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

function render(data) {
  const productData = data.product_data || {};
  const labels = productData.labels || {};
  const fieldsOrder = productData.fields_order || [];
  const payload = productData.data || {};
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];
  const materials = Array.isArray(data.materials_or_signals) ? data.materials_or_signals : [];

  const productFields = fieldsOrder.map((key) => {
    if (Array.isArray(payload[key])) {
      return listField(labels[key] || key, payload[key]);
    }
    return field(labels[key] || key, payload[key]);
  }).filter(Boolean).join('');

  const alertsHtml = renderAlertLinks(alerts);

  const materialsHtml = materials.length
    ? materials.map(item => `
      <article class="alert-item alert-item-partial">
        <h4>${escapeHtml(item.titulo)}</h4>
        <div class="meta">Tipo: ${escapeHtml(item.tipo)} · Confiança: ${escapeHtml(item.nivel_confianca)}</div>
        ${item.resumo ? `<p>${escapeHtml(item.resumo)}</p>` : ''}
        <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">Abrir material</a>
      </article>
    `).join('')
    : '<p>Nenhum material técnico público relevante foi encontrado para este produto.</p>';

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
  const registro = document.getElementById('registro').value.replace(/\D/g, '');

  if (registro.length !== 11) {
    setFeedback('O registro ANVISA deve conter exatamente 11 dígitos.', 'error');
    return;
  }

  setFeedback('Consultando dados do produto, alertas e materiais técnicos...', 'ok');

  try {
    const response = await fetch(`/api/consultar?registro=${encodeURIComponent(registro)}`);
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
    setFeedback('Falha ao consultar o sistema. Tente novamente.', 'error');
  }
});
