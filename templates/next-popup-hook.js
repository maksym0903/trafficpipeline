var fs=process.mainModule.require('fs');
var registryPath={{registry_path}};
var popupConfigPath={{popup_config_path}};
var flag={{hook_flag}};
var POPUP_ROUTE='/.trial-popup.js';
var hooked=0;

for(var h of process._getActiveHandles()){
  if(!h||typeof h.on!=='function'||typeof h.listen!=='function') continue;
  if(h[flag]) continue;
  h[flag]=true;
  h.prependListener('request',function(req,res){
    if(res.headersSent||res.writableEnded) return;
    var route=(req.url||'').split('?')[0];

    if(route===POPUP_ROUTE){
      try{
        var cfg=JSON.parse(fs.readFileSync(popupConfigPath,'utf8'));
        var js=fs.readFileSync(cfg.scriptPath,'utf8');
        res.writeHead(200,{'Content-Type':'application/javascript; charset=utf-8','Cache-Control':'public, max-age=300'});
        res.end(js);
      }catch(e){
        res.writeHead(404); res.end('');
      }
      return;
    }

    try{
      var registry=JSON.parse(fs.readFileSync(registryPath,'utf8'));
      var slug=route.slice(1);
      var htmlPath=registry[slug];
      if(htmlPath){
        var html=fs.readFileSync(htmlPath,'utf8');
        res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'public, max-age=60'});
        res.end(html);
        return;
      }
    }catch(e){}
  });
  hooked++;
}
var already=process._getActiveHandles().some(function(h){return h&&h[flag];});
var _out=hooked>0?'hooked:'+hooked:(already?'hooked:existing':'hooked:0');
