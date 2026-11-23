// Compila uma entrada JSON padrao com um soljson especifico (compilador oficial em JavaScript), usado nas versoes
// nightly, nas anteriores a 0.4.11 (sem --standard-json) e nas que nao tem binario windows oficial da versao longa
// exata. Uso: node solcjs.js <caminho-do-soljson> < entrada.json > saida.json
const fs = require("fs");
const wrapper = require("solc/wrapper");

const soljson = require(require("path").resolve(process.argv[2]));
const solc = wrapper(soljson);
const entrada = fs.readFileSync(0, "utf8");
const saida = solc.compile(entrada);
process.stdout.write(typeof saida === "string" ? saida : JSON.stringify(saida));
