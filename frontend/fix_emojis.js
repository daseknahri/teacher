import fs from 'fs';

const files = [
  'src/views/WorkflowView.js',
  'src/views/ClassView.js',
  'src/views/ExamView.js',
  'src/views/OwnerView.js',
  'src/views/CalendarView.js',
  'src/views/LoginView.js'
];

for (const f of files) {
  let text;
  try { text = fs.readFileSync(f, 'utf8'); } catch (e) { continue; }
  
  text = text.replace(/------x\x18------/g, '');
  text = text.replace(/------a"------/g, '');
  text = text.replace(/------\x13------/g, '');
  text = text.replace(/------x\x1c\x13/g, '');
  text = text.replace(/------x\x1c\x18------/g, '');
  text = text.replace(/------x\x1c9/g, '');
  text = text.replace(/=------/g, '');
  text = text.replace(/------R/g, '');
  text = text.replace(/------S\x1c/g, '');
  text = text.replace(/------\x13/g, '');
  text = text.replace(/------x\x1c\x1e/g, '');
  text = text.replace(/------S/g, '');
  text = text.replace(/------x\x19------/g, '');
  text = text.replace(/------x\x1c------/g, '');
  text = text.replace(/------\x1d/g, '');
  text = text.replace(/------\x19/g, '');
  text = text.replace(/------/g, '');
  
  fs.writeFileSync(f, text);
}
