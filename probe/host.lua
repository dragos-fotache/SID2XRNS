-- SPDX-License-Identifier: AGPL-3.0-only
-- Installed only into a private, generated Renoise profile.
local json = require('mcp.json')
local f = assert(io.open(renoise.tool().bundle_path .. 'sid2xrns-root.txt'))
local root, profile = f:read('*l'), f:read('*l'); f:close()
local switches = 0
local function reply(x) return {content={{type='text',text=json.encode(x)}}} end
local function own()
  assert(renoise.app().log_filename:find(profile .. '/Renoise/V3.5.4/',1,true)==1,'Wrong private profile')
  local p=assert(io.open('/proc/self/stat')); local pid=tonumber(p:read('*l'):match('^(%d+)'));p:close()
  return pid
end
local function path(name)
  assert(type(name)=='string' and name:match('^[%w_.-]+$') and not name:find('..',1,true),'Simple scratch filename required')
  return root .. '/' .. name
end
local function info()
  local s=renoise.song();local x={pid=own(),file=s.file_name,name=s.name,playing=s.transport.playing,
    bpm=s.transport.bpm,lpb=s.transport.lpb,tpl=s.transport.tpl,version=renoise.RENOISE_VERSION,
    sequence=s.sequencer.pattern_sequence,patterns={},instruments={},tracks={}}
  for i,p in ipairs(s.patterns)do x.patterns[i]={lines=p.number_of_lines,name=p.name}end
  for i,v in ipairs(s.instruments) do
    local pp=v.plugin_properties;local z={channel=pp.channel,alias=pp.alias_instrument_index,name=v.name}
    if pp.plugin_device then
      z.path=pp.plugin_device.device_path;z.parameters={}
      for j,p in ipairs(pp.plugin_device.parameters) do z.parameters[j]={name=p.name,value=p.value,text=p.value_string} end
    end
    x.instruments[i]=z
  end
  for i,t in ipairs(s.tracks) do
    local z={name=t.name,devices={}}
    for j,d in ipairs(t.devices)do
      local q={path=d.device_path,parameters={}}
      for k,p in ipairs(d.parameters)do q.parameters[k]={name=p.name,value=p.value}end
      z.devices[j]=q
    end
    x.tracks[i]=z
  end
  return x
end
local function handler(a)
  own(); local s=renoise.song()
  if a.operation=='inspect' then return reply(info()) end
  if a.operation=='seed' then
    for _,i in ipairs(s.instruments)do
      assert(not i.plugin_properties.plugin_loaded,'Seed requires an empty song')
      for _,v in ipairs(i.samples)do assert(not v.sample_buffer.has_sample_data,'Song contains samples')end
    end
    for _,p in ipairs(s.patterns)do assert(p.is_empty,'Song contains notes')end
    s.name='SID2XRNS timing seed'
    while #s.instruments<3 do s:insert_instrument_at(#s.instruments+1)end
    while #s.instruments>3 do s:delete_instrument_at(#s.instruments)end
    while s.sequencer_track_count>3 do s:delete_track_at(s.sequencer_track_count)end
    while s.sequencer_track_count<3 do s:insert_track_at(s.sequencer_track_count+1)end
    local found
    for _,p in ipairs(s.instruments[1].plugin_properties.available_plugin_infos)do
      if p.name:find('SID XRNS Timing Probe',1,true)then found=p.path;break end
    end
    assert(found,'Timing probe not scanned')
    assert(s.instruments[1].plugin_properties:load_plugin(found))
    s.instruments[1].plugin_properties.auto_suspend=false
    for i=1,3 do s.instruments[i].plugin_properties.channel=i;s.tracks[i].name='SID part '..i end
    s.tracks[1]:insert_device_at('Audio/Effects/Native/*Instr. Automation',2)
    renoise.app():save_song_as(path(a.name or 'seed.xrns'))
  elseif a.operation=='load' then
    local p=path(a.name);assert(p:match('%.xrns$'))
    -- Saving our current scratch song avoids the modal unsaved-change prompt.
    -- Never discard data or invoke a dialog from the deferred switch callback.
    assert(s.file_name:find(root..'/',1,true)==1,'Save the private scratch song first')
    switches=switches+1
    renoise.app():save_song_as(path('before-switch-'..own()..'-'..switches..'.xrns'))
    local cb;cb=function()renoise.tool():remove_timer(cb);renoise.app():load_song(p)end
    renoise.tool():add_timer(cb,100);return reply({loading=p,pid=own()})
  else
    assert(s.file_name:find(root..'/',1,true)==1,'Open this project scratch song')
    if a.operation=='save' then renoise.app():save_song_as(path(a.name))
    elseif a.operation=='capture' then
      local d=assert(s.instruments[1].plugin_properties.plugin_device)
      assert(d.name:find('SID XRNS Timing Probe',1,true),'Timing probe required')
      assert(d.parameters[#d.parameters].name=='Capture')
      d.parameters[#d.parameters].value=tonumber(a.value)
    elseif a.operation=='play' then
      s.transport:stop();s.transport.loop_pattern=false
      s.transport:start_at(renoise.SongPos(1,1))
    elseif a.operation=='stop' then s.transport:stop()
    else error('Unknown operation')end
  end
  return reply(info())
end
return {{name='xrns_timing',description='Private SID2XRNS timing fixture only',
  inputSchema={type='object',properties={operation={type='string'},name={type='string'},value={type='number'}},required={'operation'}},handler=handler}}
