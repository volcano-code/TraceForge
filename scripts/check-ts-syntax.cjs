// A syntax check only. This deliberately does not claim full TypeScript checking.
const fs=require('node:fs'),path=require('node:path');
const ts=require('typescript');
const root=path.resolve(__dirname,'../frontend');let count=0,errors=[];
function visit(dir){for(const name of fs.readdirSync(dir)){const file=path.join(dir,name);if(fs.statSync(file).isDirectory()){if(name!=='node_modules'&&name!=='dist')visit(file);}else if(/\.tsx?$/.test(name)&&!name.endsWith('.d.ts')){
const result=ts.transpileModule(fs.readFileSync(file,'utf8'),{fileName:file,reportDiagnostics:true,compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.ReactJSX}});count++;errors.push(...(result.diagnostics||[]).filter(d=>d.category===ts.DiagnosticCategory.Error));}}}
visit(root);for(const e of errors)console.error(ts.flattenDiagnosticMessageText(e.messageText,'\n'));
console.log(JSON.stringify({check:'TypeScript syntax only; NOT full typecheck/build',files:count,errors:errors.length}));process.exitCode=errors.length?1:0;
