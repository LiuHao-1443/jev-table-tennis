try { new Function(readFile('tests/.build_plain.js')); print('SYNTAX OK'); }
catch (e) { print('SYNTAX ERROR: ' + e); }
