import { parseRoman } from './roman-parse.js';

const input = document.getElementById('roman-input');
const evaluateBtn = document.getElementById('evaluate-btn');
const resetBtn = document.getElementById('reset-btn');
const display = document.getElementById('display');

function evaluate() {
  const roman = input.value.trim();
  try {
    const arabic = parseRoman(roman);
    const row = document.createElement('div');
    row.className = 'list-group-item';
    row.textContent = `${roman} = ${arabic}`;
    display.appendChild(row);
  } catch (err) {
    alert(err.message);
  }
}

function reset() {
  input.value = '';
  display.textContent = '';
}

evaluateBtn.addEventListener('click', evaluate);
resetBtn.addEventListener('click', reset);
input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    evaluate();
  }
});
