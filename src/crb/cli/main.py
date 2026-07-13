"""CLI entry point for CodeReviewerBot.

Usage:
    crb review <paths>              # Auto-detect language, review all
    crb review --lang python <path> # Explicitly specify language
    crb list-langs                  # List supported languages
    crb list-sort-presets           # List sort order options
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import fnmatch

import click

from crb.config.settings import AppConfig, LLMConfig
from crb.llm.client import LLMError, chat
from crb.report.models import OutputLang, ReviewReport, Severity
from crb.report.structure_builder import generate_structure_json as _build_structure_json

_PRESET_SORT_ORDERS = {
    "default": [Severity.BLOCKER, Severity.CRITICAL, Severity.MAJOR],
    "severity-up": [Severity.MAJOR, Severity.CRITICAL, Severity.BLOCKER],
    "critical-first": [Severity.CRITICAL, Severity.BLOCKER, Severity.MAJOR],
}


def _resolve_sort_order(sort: str) -> list[Severity]:
    if sort in _PRESET_SORT_ORDERS:
        return _PRESET_SORT_ORDERS[sort]
    try:
        return [Severity[s.upper().strip()] for s in sort.split(",")]
    except (KeyError, ValueError):
        click.echo(f"Warning: invalid sort order '{sort}', using default.", err=True)
        return _PRESET_SORT_ORDERS["default"]


def _run_analyzer(
    lang: str, files: list[str], config: AppConfig, sort_order: list[Severity], output_lang: str
) -> ReviewReport:
    """Dispatch to the appropriate language analyzer."""
    if lang == "python":
        from crb.analyzers.python.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    elif lang == "c_cpp":
        from crb.analyzers.c_cpp.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    elif lang == "go":
        from crb.analyzers.go.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    elif lang == "rust":
        from crb.analyzers.rust.reporter import analyze_files
        return analyze_files(files, config=config, sort_order=sort_order, output_lang=output_lang)
    else:
        raise ValueError(f"Unsupported language: {lang}")


_STRUCTURE_VIEWER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Project Structure</title>
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f6fa;color:#2c3e50;padding:0}
.header{padding:24px 24px 0;max-width:1200px;margin:0 auto}
.header h1{font-size:24px;font-weight:600;color:#1a1a2e}
.header .meta{color:#7f8c8d;font-size:14px;margin-top:4px}
.tabs{display:flex;border-bottom:2px solid #e8ecf1;margin:20px 24px 0;max-width:1200px;margin-left:auto;margin-right:auto;overflow-x:auto}
.tab{padding:12px 20px;cursor:pointer;font-size:14px;font-weight:500;color:#7f8c8d;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .2s;user-select:none;white-space:nowrap}
.tab:hover{color:#2c3e50}
.tab.active{color:#3498db;border-bottom-color:#3498db}

.content{max-width:1200px;margin:0 auto;padding:24px}
.search-bar{width:100%;max-width:1200px;margin:0 auto;padding:0 24px 16px}
.search-bar input{width:100%;padding:10px 16px;border:1px solid #e0e0e0;border-radius:8px;font-size:14px;outline:none;transition:border .2s;background:#fff}
.search-bar input:focus{border-color:#3498db;box-shadow:0 0 0 3px rgba(52,152,219,.15)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-bottom:32px}
.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);border:1px solid #e8ecf1;cursor:pointer;transition:all .2s}
.card:hover{box-shadow:0 4px 12px rgba(0,0,0,.12);transform:translateY(-2px)}
.card h3{font-size:15px;font-weight:600;margin-bottom:8px;color:#1a1a2e}
.card .count{font-size:28px;font-weight:700;color:#3498db}
.card .sub{font-size:12px;color:#95a5a6;margin-top:4px}
.stats-row{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}
.stat-box{background:#fff;border-radius:10px;padding:16px 24px;border:1px solid #e8ecf1;flex:1;min-width:120px}
.stat-box .num{font-size:22px;font-weight:700;color:#1a1a2e}
.stat-box .label{font-size:12px;color:#95a5a6;margin-top:2px}
.stat-box.accent{border-left:3px solid #3498db}
.stat-box.warn{border-left:3px solid #e67e22}

.file-list{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);border:1px solid #e8ecf1;overflow:hidden}
.file-header{padding:14px 20px;border-bottom:1px solid #e8ecf1;font-weight:600;font-size:14px;display:flex;justify-content:space-between;align-items:center}
.file-header .toggle{color:#3498db;font-size:13px;cursor:pointer;user-select:none}
.file-row{display:flex;align-items:center;padding:10px 20px;border-bottom:1px solid #f0f2f5;font-size:13px;transition:background .15s;cursor:pointer}
.file-row:last-child{border-bottom:none}
.file-row:hover{background:#f0f4ff}
.file-row.selected{background:#eaf4ff}
.file-row .name{font-family:'SF Mono',Menlo,monospace;color:#2c3e50;font-weight:500}
.file-row .path{color:#95a5a6;font-size:12px;margin-left:12px;flex:1}
.file-row .module{background:#eaf2fd;color:#2980b9;padding:2px 8px;border-radius:4px;font-size:11px;white-space:nowrap}
.file-row .sym-count{font-size:11px;color:#95a5a6;margin-left:8px;white-space:nowrap}
.file-detail{background:#f8f9fb;padding:16px 20px;border-bottom:1px solid #e8ecf1;font-size:13px;line-height:1.8}
.file-detail .sclass{color:#27ae60;font-weight:500}
.file-detail .sfn{color:#8e44ad}

.tree-view{background:#fafbfc;border-radius:12px;border:1px solid #e8ecf1;overflow:hidden}
.tree-inner{padding:12px 16px;font-family:'SF Mono',Menlo,monospace;font-size:13px;line-height:1.8;max-height:600px;overflow-y:auto}
.tree-line{white-space:pre;cursor:default}
.tree-line.clickable{cursor:pointer}
.tree-line.clickable:hover{background:#f0f4ff;margin:0 -16px;padding:0 16px;border-radius:4px}
.dir-arrow{color:#95a5a6;margin-right:4px;display:inline-block;width:12px;transition:transform .2s}
.dir-arrow.open{transform:rotate(90deg)}
.tree-dir{color:#2c3e50;font-weight:500}
.tree-file{color:#555;cursor:pointer}
.tree-file:hover{color:#3498db}
.sym-badge{font-size:10px;color:#95a5a6;margin-left:4px}

.module-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-top:16px}
.module-card{padding:14px 16px;background:#f8f9fb;border-radius:8px;border-left:3px solid #3498db;cursor:pointer}
.module-card:hover{background:#f0f4ff}
.module-card h4{font-size:14px;margin-bottom:4px;color:#2c3e50}
.module-card .file-count{font-size:12px;color:#95a5a6}
.module-card .files{margin-top:8px;padding-left:12px;border-left:2px solid #e8ecf1}
.module-card .files div{font-size:12px;padding:2px 0;font-family:'SF Mono',Menlo,monospace;color:#555;cursor:pointer}
.module-card .files div:hover{color:#3498db}

.dep-node{display:flex;align-items:center;padding:8px 16px;border-bottom:1px solid #f0f2f5;font-size:13px;cursor:pointer;transition:background .15s}
.dep-node:hover{background:#f0f4ff}
.dep-node:last-child{border-bottom:none}
.dep-name{font-weight:500;color:#2c3e50;min-width:160px}
.dep-bar-wrap{flex:1;height:16px;background:#e8ecf1;border-radius:8px;overflow:hidden;margin:0 12px}
.dep-bar{height:100%;background:#3498db;border-radius:8px;transition:width .3s}
.dep-count{color:#95a5a6;font-size:12px;min-width:60px;text-align:right}
.dep-files{margin-top:4px;padding:8px 16px 16px;border-bottom:1px solid #e8ecf1;display:none}
.dep-files.open{display:block}
.dep-file{font-size:12px;padding:3px 0;font-family:'SF Mono',Menlo,monospace;color:#555;cursor:pointer}
.dep-file:hover{color:#3498db}

.empty-state{text-align:center;padding:60px 20px;color:#95a5a6;font-size:15px}
.no-match{text-align:center;padding:40px 20px;color:#95a5a6;font-size:14px}
.page-nav{display:flex;justify-content:center;align-items:center;gap:8px;padding:16px}
.page-btn{width:32px;height:32px;border:1px solid #e0e0e0;border-radius:6px;background:#fff;cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center;transition:all .15s;user-select:none}
.page-btn:hover{background:#f0f4ff;border-color:#3498db}
.page-btn.active{background:#3498db;color:#fff;border-color:#3498db}
.page-btn:disabled{opacity:.3;cursor:default}
.page-info{font-size:13px;color:#7f8c8d;padding:0 8px}

@media(prefers-color-scheme:dark){
body{background:#0f0f1a;color:#e0e0e0}
.card,.file-list,.tree-view,.stat-box,.module-card,.search-bar input{background:#1a1a2e;border-color:#2a2a3e}
.card:hover{box-shadow:0 4px 12px rgba(0,0,0,.3)}
.file-row:hover,.file-row.selected{background:#22223a}
.file-detail{background:#22223a}
.tree-inner{background:#1a1a2e;border-color:#2a2a3e}
.tree-line.clickable:hover{background:#22223a}
.file-header{border-color:#2a2a3e}.file-row{border-color:#22223a}
.dep-node:hover{background:#22223a}
.dep-bar-wrap{background:#2a2a3e}
.module-card{background:#22223a;border-color:#2a2a3e}
.module-card:hover{background:#2a2a3e}
.tabs{border-bottom-color:#2a2a3e}.tab{color:#7f8c8d}.tab.active{color:#5dade2}
.search-bar input{color:#e0e0e0;background:#1a1a2e;border-color:#2a2a3e}
.search-bar input:focus{border-color:#5dade2}
.page-btn{background:#1a1a2e;border-color:#2a2a3e;color:#e0e0e0}
.page-btn:hover{background:#22223a;border-color:#5dade2}
.page-btn.active{background:#5dade2;color:#fff;border-color:#5dade2}
}
</style>
</head>
<body>
<div id="root"></div>
<script>
const DATA = __STRUCTURE_DATA__;
const {useState,useMemo,useCallback} = React;
const PAGE_SIZE = 30;

const TABS = [
  {key:'overview', label:'概览'},
  {key:'tree', label:'文件树'},
  {key:'files', label:'文件列表'},
  {key:'modules', label:'模块详情'},
  {key:'deps', label:'依赖关系'},
];

function StatBox({num,label,accent,warn}) {
  return React.createElement('div',{className:'stat-box'+(accent?' accent':'')+(warn?' warn':'')},
    React.createElement('div',{className:'num'},num),
    React.createElement('div',{className:'label'},label)
  );
}

function OverviewTab({modules,files,imports}) {
  const totalFiles = files.length;
  const totalImports = imports.length;
  const totalModules = modules.length;
  const totalSymbols = files.reduce((s,f)=>s+(f.symbols?f.symbols.length:0),0);
  return React.createElement(React.Fragment,null,
    React.createElement('div',{className:'stats-row'},
      React.createElement(StatBox,{num:totalFiles,label:'源文件',accent:true}),
      React.createElement(StatBox,{num:totalModules,label:'模块'}),
      React.createElement(StatBox,{num:totalSymbols,label:'符号（类/函数）'}),
      React.createElement(StatBox,{num:totalImports,label:'依赖',warn:totalImports>0})
    ),
    React.createElement('div',{className:'grid'},
      modules.map(mod=>React.createElement('div',{key:mod.name,className:'card'},
        React.createElement('h3',null,mod.label),
        React.createElement('div',{className:'count'},mod.file_count),
        React.createElement('div',{className:'sub'},'files')
      ))
    )
  );
}

function buildTree(modules,files){
  const tree={}; const seen=new Set();
  const add=(parts,i,file)=>{
    if(i>=parts.length)return;
    const p=parts[i]; const isLast=i===parts.length-1;
    if(!tree[p]){tree[p]={__files:[],__dirs:{},__dirOrder:[]}}
    if(isLast){tree[p].__files.push(file)}
    else{add(parts,i+1,file)}
  };
  modules.forEach(m=>{
    const parts=m.name.split('/');
    tree[parts[0]]=tree[parts[0]]||{__files:[],__dirs:{},__dirOrder:[]};
  });
  return tree;
}

function TreeNode({node,path,level,onSelectFile}) {
  const [open,setOpen]=useState(level<2);
  const entries=Object.entries(node).filter(([k])=>k!=='__files');
  const files=node.__files||[];
  const hasChildren=entries.length>0||files.length>0;
  const arrow=hasChildren?(open?'▾':'▸'):' ';
  return React.createElement(React.Fragment,null,
    React.createElement('div',{className:'tree-line'+(hasChildren?' clickable':''),onClick:()=>hasChildren&&setOpen(!open),style:{paddingLeft:level*16+'px'}},
      React.createElement('span',{className:'dir-arrow'+(open?' open':'')},arrow),
      React.createElement('span',{className:'tree-dir'},path.split('/').pop()||path),
      React.createElement('span',{style:{color:'#95a5a6',fontSize:'12px',marginLeft:'6px'}},'('+ (entries.length+files.length)+')')
    ),
    open&&entries.map(([k,v])=>React.createElement(TreeNode,{key:k,node:v,path:k,level:level+1,onSelectFile:onSelectFile})),
    open&&files.map(f=>React.createElement('div',{key:f,className:'tree-line',style:{paddingLeft:(level+1)*16+'px'},onClick:(e)=>{e.stopPropagation();onSelectFile&&onSelectFile(f)}},
      React.createElement('span',{style:{display:'inline-block',width:'12px'}},' '),
      React.createElement('span',{className:'tree-file'},f)
    ))
  );
}

function TreeTab({modules,files,onSelectFile}) {
  const tree=useMemo(()=>buildTree(modules,files),[modules,files]);
  const roots=Object.entries(tree);
  if(!modules.length) return React.createElement('div',{className:'empty-state'},'暂无模块数据');
  return React.createElement('div',{className:'tree-view'},
    React.createElement('div',{className:'tree-inner'},
      roots.map(([k,v])=>React.createElement(TreeNode,{key:k,node:v,path:k,level:0,onSelectFile:onSelectFile}))
    )
  );
}

function FileDetail({file,files}) {
  if(!file) return null;
  const detail=files.find(f=>f.name===file);
  if(!detail) return null;
  const syms=detail.symbols||[];
  return React.createElement('div',{className:'file-detail'},
    React.createElement('div',{style:{fontWeight:600,marginBottom:'8px'}},detail.path),
    syms.length>0?React.createElement('div',null,
      syms.map((s,i)=>React.createElement('div',{key:i},
        React.createElement('span',{className:s.name.startsWith('class')?'sclass':'sfn'},s.name),
        s.children&&s.children.length>0?React.createElement('span',{style:{color:'#95a5a6'}},': '+s.children.join(', ')):null
      ))
    ):React.createElement('span',{style:{color:'#95a5a6'}},'无符号信息')
  );
}

function Pagination({page,totalPages,onPage}) {
  if(totalPages<=1)return null;
  const pages=[];
  const start=Math.max(0,Math.min(page-2,totalPages-5));
  const end=Math.min(start+5,totalPages);
  for(let i=start;i<end;i++)pages.push(i);
  return React.createElement('div',{className:'page-nav'},
    React.createElement('button',{className:'page-btn',disabled:page===0,onClick:()=>onPage(page-1)},'‹'),
    pages.map(p=>React.createElement('button',{key:p,className:'page-btn'+(p===page?' active':''),onClick:()=>onPage(p)},p+1)),
    React.createElement('button',{className:'page-btn',disabled:page>=totalPages-1,onClick:()=>onPage(page+1)},'›'),
    React.createElement('span',{className:'page-info'},(page+1)+'/'+totalPages)
  );
}

function FilesTab({files,search,selectedFile,onSelectFile}) {
  const [page,setPage]=useState(0);
  const filtered=useMemo(()=>{
    if(!search)return files;
    const q=search.toLowerCase();
    return files.filter(f=>f.name.toLowerCase().includes(q)||f.path.toLowerCase().includes(q));
  },[files,search]);
  const totalPages=Math.ceil(filtered.length/PAGE_SIZE);
  const visible=filtered.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);

  React.useEffect(()=>{setPage(0)},[search]);

  if(!filtered.length)return React.createElement('div',{className:'no-match'},search?'无匹配文件':'暂无数据');
  return React.createElement('div',null,
    React.createElement(FileDetail,{file:selectedFile,files:files}),
    React.createElement('div',{className:'file-list'},
      React.createElement('div',{className:'file-header'},
        React.createElement('span',null,'文件 ('+filtered.length+(filtered.length<files.length?'/'+files.length:'')+')'),
        React.createElement('span',null)
      ),
      visible.map(f=>{
        const symCount=f.symbols?f.symbols.length:0;
        return React.createElement('div',{key:f.path,className:'file-row'+(selectedFile===f.name?' selected':''),onClick:()=>onSelectFile(selectedFile===f.name?null:f.name)},
          React.createElement('span',{className:'name'},f.name),
          React.createElement('span',{className:'path'},f.path),
          f.module?React.createElement('span',{className:'module'},f.module):null,
          symCount>0?React.createElement('span',{className:'sym-count'},symCount+' sym'):null
        );
      })
    ),
    React.createElement(Pagination,{page,pageNum:page,totalPages,onPage:p=>setPage(p)})
  );
}

function ModuleCard({mod,files,onSelectFile}) {
  const [expanded,setExpanded]=useState(false);
  const modFiles=files.filter(f=>f.module===mod.name);
  return React.createElement('div',{className:'module-card',onClick:()=>setExpanded(!expanded)},
    React.createElement('h4',null,mod.label),
    React.createElement('div',{className:'file-count'},mod.file_count+' files'),
    expanded&&React.createElement('div',{className:'files'},
      modFiles.slice(0,30).map(f=>React.createElement('div',{key:f.path,onClick:(e)=>{e.stopPropagation();onSelectFile&&onSelectFile(f.name)}},f.name)),
      modFiles.length>30?React.createElement('div',{style:{color:'#95a5a6',fontSize:'12px',padding:'4px 0'}},'... 还有 '+(modFiles.length-30)+' 个文件'):null
    )
  );
}

function ModulesTab({modules,files,search,onSelectFile}) {
  const filtered=useMemo(()=>{
    if(!search)return modules;
    const q=search.toLowerCase();
    return modules.filter(m=>m.name.toLowerCase().includes(q));
  },[modules,search]);
  if(!filtered.length)return React.createElement('div',{className:'no-match'},search?'无匹配模块':'暂无模块数据');
  return React.createElement('div',{className:'module-card-grid'},
    filtered.map(mod=>React.createElement(ModuleCard,{key:mod.name,mod:mod,files:files,onSelectFile:onSelectFile}))
  );
}

function DepsTab({imports,search}) {
  const [expanded,setExpanded]=useState(null);
  const byTarget={};
  imports.forEach(i=>{byTarget[i.target]=byTarget[i.target]||[];byTarget[i.target].push(i.from)});
  let entries=Object.entries(byTarget).sort((a,b)=>b[1].length-a[1].length);
  const maxCount=entries.length>0?entries[0][1].length:1;
  const filtered=search?entries.filter(([name])=>name.toLowerCase().includes(search.toLowerCase())):entries;
  if(!filtered.length)return React.createElement('div',{className:'no-match'},search?'无匹配依赖':'暂无数据');
  return React.createElement('div',{className:'file-list'},
    React.createElement('div',{className:'file-header'},
      React.createElement('span',null,'依赖 ('+imports.length+', '+filtered.length+' 项)')
    ),
    filtered.slice(0,80).map(([target,files])=>{
      const pct=Math.round((files.length/maxCount)*100);
      return React.createElement(React.Fragment,{key:target},
        React.createElement('div',{className:'dep-node',onClick:()=>setExpanded(expanded===target?null:target)},
          React.createElement('span',{className:'dep-name'},target),
          React.createElement('div',{className:'dep-bar-wrap'},
            React.createElement('div',{className:'dep-bar',style:{width:pct+'%'}})
          ),
          React.createElement('span',{className:'dep-count'},files.length+' 处')
        ),
        expanded===target?React.createElement('div',{className:'dep-files open'},
          files.slice(0,20).sort().map(f=>React.createElement('div',{key:f,className:'dep-file'},f)),
          files.length>20?React.createElement('div',{style:{color:'#95a5a6',fontSize:'12px',padding:'4px 0'}},'... 还有 '+(files.length-20)+' 处'):null
        ):null
      );
    })
  );
}

function App() {
  const [tab,setTab]=useState('overview');
  const [search,setSearch]=useState('');
  const [selectedFile,setSelectedFile]=useState(null);
  const {modules=[],files=[],imports=[]}=DATA;
  const totalFiles=files.length;

  const tabEl=useMemo(()=>{
    switch(tab){
      case 'overview': return React.createElement(OverviewTab,{modules,files,imports,key:'ov'});
      case 'tree': return React.createElement(TreeTab,{modules,files,onSelectFile:setSelectedFile,key:'tr'});
      case 'files': return React.createElement(FilesTab,{files,search,selectedFile,onSelectFile:setSelectedFile,key:'fi'});
      case 'modules': return React.createElement(ModulesTab,{modules,files,search,onSelectFile:setSelectedFile,key:'mo'});
      case 'deps': return React.createElement(DepsTab,{imports,search,key:'de'});
      default: return React.createElement('div',{className:'empty-state'},'未知标签');
    }
  },[tab,search,selectedFile,modules,files,imports]);

  const showSearch=tab==='files'||tab==='modules'||tab==='deps';

  return React.createElement(React.Fragment,null,
    React.createElement('div',{className:'header'},
      React.createElement('h1',null,'项目结构'),
      React.createElement('div',{className:'meta'},totalFiles+' 个文件, '+modules.length+' 个模块'+(imports.length?', '+imports.length+' 个依赖':''))
    ),
    React.createElement('div',{className:'tabs'},
      TABS.map(t=>React.createElement('div',{key:t.key,className:'tab'+(tab===t.key?' active':''),onClick:()=>setTab(t.key)},t.label))
    ),
    showSearch?React.createElement('div',{className:'search-bar'},
      React.createElement('input',{placeholder:'搜索...',value:search,onChange:e=>{setSearch(e.target.value);setSelectedFile(null)}})
    ):null,
    React.createElement('div',{className:'content'},tabEl)
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));
</script>
</body>
</html>"""


def _write_structure_viewer(report: ReviewReport, output_dir: str) -> None:
    """Write structure-data.json and structure-viewer.html for human browsing."""
    import json

    viewer_dir = Path(output_dir) / "viewer"
    viewer_dir.mkdir(parents=True, exist_ok=True)

    all_files = report.all_files or []
    data = _build_structure_json(all_files, viewer_dir)
    json_path = viewer_dir / "structure-data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    html = _STRUCTURE_VIEWER_TEMPLATE.replace("__STRUCTURE_DATA__", json.dumps(data, ensure_ascii=False))
    html_path = viewer_dir / "structure-viewer.html"
    html_path.write_text(html, encoding="utf-8")
    click.echo(f"Structure viewer: {html_path}")


def _write_report(
    report: ReviewReport,
    report_dir: str,
    project_name: str,
    output_format: str,
    project_root: str | None = None,
    app_config: AppConfig | None = None,
    no_react: bool = False,
) -> None:
    """Write report and structure docs to disk."""
    report_path = Path(report_dir) / f"{project_name}_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "markdown":
        # Run LLM-powered review agents to add deep semantic findings
        if app_config and app_config.llm.is_valid() and report.findings is not None:
            try:
                from crb.agents.review_agent import analyze_files as llm_review
                llm_files = list(report.all_files) if report.all_files else []
                if not llm_files and project_root:
                    root_path = Path(project_root)
                    for ext in ("*.py",):
                        llm_files.extend(str(f) for f in root_path.rglob(ext) if not any(
                            p.startswith(".") for p in f.parts
                        ))
                if llm_files:
                    llm_findings = llm_review(
                        llm_files[:20],  # limit to 20 files per run
                        config=app_config,
                        project_root=project_root,
                        report=report,  # pass report for fix suggestions
                    )
                    for f in llm_findings:
                        report.add_finding(f)
                    if llm_findings:
                        click.echo(f"LLM review: {len(llm_findings)} finding(s)")
            except Exception as e:
                click.echo(f"  (LLM review skipped: {e})", err=True)

        content = report.to_markdown()
        report_path.write_text(content, encoding="utf-8")

        # Write structure docs to project root (not inside report/)
        structure_root = project_root or report_dir
        structure_paths = report.generate_hierarchical_structure_docs(structure_root)
        for sp in structure_paths:
            click.echo(f"Structure doc: {sp}")

        # Write structure data JSON + React viewer to report/viewer/ (unless --no-react)
        if not no_react:
            _write_structure_viewer(report, report_dir)

        # Enhance structure docs with LLM
        if project_root and app_config and app_config.llm.is_valid():
            try:
                from crb.agents.structure_agent import StructureDocAgent
                agent = StructureDocAgent(app_config)
                enhanced = agent.enhance_all(project_root)
                if enhanced:
                    click.echo(f"Enhanced {len(enhanced)} structure doc(s) with LLM")
            except Exception as e:
                click.echo(f"  (structure enhancement skipped: {e})", err=True)
    else:
        json_path = report_path.with_suffix(".json")
        data = {
            "target": report.target,
            "blocker": report.blocker_count,
            "critical": report.critical_count,
            "major": report.major_count,
            "findings": [f.to_dict() for f in report.findings],
        }
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        click.echo(f"Report written to {json_path}")
        return

    click.echo(f"Report written to {report_path}")
    click.echo(
        f"Summary: {report.blocker_count} Blocker, "
        f"{report.critical_count} Critical, "
        f"{report.major_count} Major"
    )


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """CodeReviewerBot — AI-powered code review."""


@cli.command()
@click.argument("paths", nargs=-1, required=True)
@click.option("--lang", "-l", default=None, help="Language override: python, c_cpp, go, rust")
@click.option(
    "--sort", default="default",
    help="Sort order. Presets: default, severity-up, critical-first. Or custom: 'Blocker,Critical,Major'.",
)
@click.option("--output", "-o", type=click.Choice(["markdown", "json"]), default="markdown")
@click.option("--report-dir", default=None)
@click.option(
    "--output-lang", type=click.Choice(["ch", "en", "ch_en"]), default="ch",
    help="Report language: ch (Chinese), en (English), ch_en (bilingual).",
)
@click.option(
    "--exclude", multiple=True, default=[],
    help="Exclude files/dirs matching glob pattern. Can be repeated. E.g.: --exclude 'data/*' --exclude '*.txt'",
)
@click.option(
    "--no-react", is_flag=True, default=False,
    help="Skip generating the React structure viewer page.",
)
def review(paths, lang, sort, output, report_dir, output_lang, exclude, no_react):
    """Review source code in PATHS (files or directories).

    Detects language automatically from file extensions unless --lang is given.
    """
    from crb.analyzers.detector import Lang, detect

    # Load LLM config from environment
    llm_config = LLMConfig.from_env()
    config = AppConfig(report_dir=report_dir, llm=llm_config)

    # LLM is optional — static analyzers work without it, only LLM agents are skipped
    if not llm_config.is_valid():
        click.echo("Note: LLM not configured — LLM-powered agents will be skipped.", err=True)
        click.echo("  Set CRB_LLM_API_URL and CRB_LLM_API_KEY to enable deep semantic review.", err=True)

    sort_order = _resolve_sort_order(sort)

    # Resolve all paths
    resolved = []
    for p in paths:
        rp = str(Path(p).resolve())
        if not os.path.exists(rp):
            click.echo(f"Warning: path not found: {p}", err=True)
            continue
        resolved.append(rp)

    if not resolved:
        click.echo("No valid paths provided.", err=True)
        sys.exit(1)

    # Detect or override language
    detection = detect(resolved)

    if lang:
        # Explicit language override
        target_langs = [lang]
    else:
        target_langs = detection.detected_langs
        if not target_langs:
            click.echo("No supported source files found.", err=True)
            click.echo("Supported: .py, .c/.h/.cpp/.hpp, .go, .rs", err=True)
            # Still print what we found
            if detection.lang_counts.get(Lang.UNKNOWN, 0) > 0:
                click.echo(f"  ({detection.lang_counts[Lang.UNKNOWN]} unsupported files skipped)", err=True)
            sys.exit(1)

    click.echo(f"Detected: {', '.join(detection.label(lang) for lang in target_langs)}")

    # Derive project name from first resolved path
    first = resolved[0]
    project_name = os.path.basename(os.path.dirname(first)) if os.path.isfile(first) else os.path.basename(first)
    if not project_name or project_name == ".":
        project_name = os.path.basename(os.getcwd())

    # Find project root (directory containing .git) for file tree
    project_root: str | None = None
    candidate = Path(resolved[0])
    if candidate.is_file():
        candidate = candidate.parent
    for parent in [candidate] + list(candidate.parents):
        if (parent / ".git").exists():
            project_root = str(parent)
            break
    if not project_root:
        if os.path.isdir(resolved[0]):
            project_root = resolved[0]
        else:
            project_root = str(Path(resolved[0]).parent)

    # Default report_dir to inside the analyzed project, not cwd
    if report_dir is None:
        report_dir = os.path.join(project_root or os.getcwd(), "report")

    # Collect all project files for the file tree overview
    all_project_files: list[str] = []
    if project_root:
        root_path = Path(project_root)
        for f in sorted(root_path.rglob("*")):
            if f.is_file() and not any(
                part.startswith(".") or part == "archived" or part == "__pycache__"
                or part == "build" or part == "dist" or part == "node_modules" or part == "report"
                for part in f.parts
            ) and f.name not in ("structure.md",):
                all_project_files.append(str(f))

    # Apply --exclude patterns
    if exclude:
        def _should_exclude(fp: str) -> bool:
            for pattern in exclude:
                if fnmatch.fnmatch(fp, pattern) or fnmatch.fnmatch(os.path.basename(fp), pattern):
                    return True
                # Also match path segments (e.g. --exclude data matches /any/path/data/...)
                if "/" + pattern.rstrip("/") in fp:
                    return True
            return False

        n_before = len(all_project_files)
        all_project_files = [f for f in all_project_files if not _should_exclude(f)]
        n_after = len(all_project_files)
        if n_before != n_after:
            click.echo(f"Excluded {n_before - n_after} file(s) from project overview")

        # Also filter detection results so analysis doesn't run on excluded files
        for lang_key in list(detection.files.keys()):
            detection.files[lang_key] = [
                f for f in detection.files[lang_key]
                if not _should_exclude(f)
            ]

    for target_lang in target_langs:
        lang_files = detection.files.get(target_lang, [])
        if not lang_files:
            continue

        click.echo(f"Analyzing {len(lang_files)} {detection.label(target_lang)} file(s)...")
        report = _run_analyzer(target_lang, lang_files, config, sort_order, output_lang)
        report.all_files = all_project_files
        _write_report(report, report_dir, project_name, output, project_root=project_root, app_config=config, no_react=no_react)

    # Cross-language structure analysis (AI code spread detection)
    if all_project_files and len(all_project_files) >= 5:
        from crb.analyzers.generic.structure_analyzer import analyze_structure
        struct_findings = analyze_structure(all_project_files, project_root=project_root)
        if struct_findings:
            click.echo(f"Structure: found {len(struct_findings)} structural issue(s)")
            struct_report = ReviewReport(target=project_root or ", ".join(resolved), lang=OutputLang(output_lang))
            struct_report.set_sort_order(sort_order)
            for f in struct_findings:
                struct_report.add_finding(f)
            struct_report.all_files = all_project_files
            _write_report(struct_report, report_dir, f"{project_name}_structure", output, project_root=project_root, app_config=config, no_react=no_react)

    # Call chain report (main logic flow with clickable file links)
    if project_root and all_project_files:
        from crb.analyzers.call_chain import generate_call_chain_report
        cc_path = generate_call_chain_report(
            project_root, project_name,
            app_config=config,
            report_dir=report_dir,
        )
        click.echo(f"Call chain: {cc_path}")

    # Cross-language security scan (hardcoded secrets in all project files)
    if all_project_files:
        from crb.analyzers.secret_detector import analyze_file as secret_scan
        secret_findings: list = []
        for fp in all_project_files:
            secret_findings.extend(secret_scan(fp, lang=OutputLang(output_lang)))
        if secret_findings:
            click.echo(f"Security: found {len(secret_findings)} potential secret(s)")
            sec_report = ReviewReport(target="security_scan", lang=OutputLang(output_lang))
            sec_report.set_sort_order(sort_order)
            for f in secret_findings:
                sec_report.add_finding(f)
            sec_report.all_files = all_project_files
            _write_report(sec_report, report_dir, f"{project_name}_security", output, project_root=project_root, app_config=config, no_react=no_react)


@cli.command(name="build-analyzer")
def build_cpp_analyzer():
    """Build the C++ static analyzer for faster Python analysis."""
    import subprocess

    c_src = Path(__file__).resolve().parent.parent / "c_src"
    build_dir = c_src / "build"

    if not (c_src / "CMakeLists.txt").exists():
        click.echo("Error: c_src/CMakeLists.txt not found.", err=True)
        raise SystemExit(1)

    build_dir.mkdir(parents=True, exist_ok=True)

    click.echo("Configuring C++ analyzer...")
    cfg = subprocess.run(
        ["cmake", "..", "-DCMAKE_BUILD_TYPE=Release"],
        cwd=str(build_dir), capture_output=True, text=True,
    )
    if cfg.returncode != 0:
        click.echo(f"CMake configure failed:\n{cfg.stderr}", err=True)
        raise SystemExit(1)

    click.echo("Building C++ analyzer...")
    bld = subprocess.run(
        ["cmake", "--build", ".", "-j4"],
        cwd=str(build_dir), capture_output=True, text=True,
    )
    if bld.returncode != 0:
        click.echo(f"Build failed:\n{bld.stderr}", err=True)
        raise SystemExit(1)

    binary = build_dir / "static_analyzer"
    if binary.exists():
        click.echo(f"Built: {binary}")
        click.echo("Done. C++ analyzer will be used automatically on next review.")
    else:
        click.echo("Build succeeded but binary not found.", err=True)


@cli.command(name="list-langs")
def list_langs():
    """List supported programming languages."""
    click.echo("Supported languages:")
    click.echo("  python  - Python (.py)")
    click.echo("  c_cpp   - C/C++ (.c, .h, .cpp, .hpp, .cc, .cxx)")
    click.echo("  go      - Go (.go)")
    click.echo("  rust    - Rust (.rs)")


@cli.command(name="list-sort-presets")
def list_sort_presets():
    """List available sort order presets."""
    click.echo("Available sort presets:")
    for name, order in _PRESET_SORT_ORDERS.items():
        click.echo(f"  {name}: {', '.join(s.value for s in order)}")
    click.echo("\nCustom: comma-separated severity names, e.g. 'Blocker,Critical,Major'")


@cli.command()
def doctor():
    """Diagnose LLM configuration."""

    config = LLMConfig.from_env()

    click.echo("CodeReviewerBot Doctor")
    click.echo("=" * 40)

    # Check LLM config
    click.echo(f"\nLLM API URL:    {config.api_url or '(not set)'}")
    click.echo(f"LLM API Key:    {'✓ set' if config.api_key else '✗ not set'}")
    click.echo(f"LLM Model:      {config.model or '(not set, will use gpt-4o)'}")

    if not config.is_valid():
        click.echo("\n✗ LLM not configured.")
        click.echo("  Set CRB_LLM_API_URL and CRB_LLM_API_KEY in your environment.")
        click.echo("  Example:")
        click.echo('    export CRB_LLM_API_URL="https://api.openai.com/v1"')
        click.echo('    export CRB_LLM_API_KEY="sk-..."')
        click.echo('    export CRB_LLM_MODEL="gpt-4o"')
        return

    # Test connection
    click.echo("\nTesting LLM connection...")
    try:
        reply = chat(config, "You are a test assistant.", "Reply only with: OK")
        click.echo(f"✓ LLM response: {reply.strip()}")
    except LLMError as e:
        click.echo(f"✗ LLM connection failed: {e}")


@cli.command(name="init-ci")
@click.argument("path", default=".", required=False)
def init_ci(path: str) -> None:
    """Generate CI/CD template files for a target project."""
    from crb.templates.ci_templates import write_templates, generate_template_report

    project_root = os.path.abspath(path)
    written = write_templates(project_root)
    click.echo(f"Generated {len(written)} CI/CD template(s):")
    for fp in written:
        click.echo(f"  - {fp}")
    click.echo()
    click.echo(generate_template_report(project_root))
