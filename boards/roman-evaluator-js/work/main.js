import { parseRoman } from './roman.js';

const input = document.getElementById('roman-input');
const display = document.getElementById('roman-display');
const evaluateButton = document.getElementById('evaluate');
const resetButton = document.getElementById('reset');

function appendRow(roman, arabic) {
  const row = document.createElement('div');
  row.textContent = `${roman} = ${arabic}`;
  display.append(row);
}

function evaluate() {
  const raw = input.value;
  let value;
  try {
    value = parseRoman(raw);
  } catch (error) {
    alert(error.message);
    return;
  }
  appendRow(raw.trim().toUpperCase(), value);
}

function reset() {
  input.value = '';
  display.replaceChildren();
  input.focus();
}

evaluateButton.addEventListener('click', evaluate);
resetButton.addEventListener('click', reset);
input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    evaluate();
  }
});

display.dataset.ready = 'true';
