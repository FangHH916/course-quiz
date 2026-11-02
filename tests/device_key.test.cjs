'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const {createDeviceVault}=require('../static/device-key.js');
const config={base_url:'https://example.com/v1',model:'test-model',api_key:'dummy-device-key-only'};
function fixture(crypto=webcrypto){
  let record=null;
  const storage={read:async()=>record,write:async value=>{record=structuredClone(value);},clear:async()=>{record=null;}};
  return {vault:createDeviceVault(storage,crypto),storage};
}
test('opt-in encrypts settings with a nonextractable key and restores bound endpoint',async()=>{
  const {vault,storage}=fixture();
  assert.equal(await vault.load(),null);
  await vault.save(config);
  const record=await storage.read();
  assert.equal(record.key.extractable,false);
  assert.equal(JSON.stringify(record).includes(config.api_key),false);
  assert.equal(new TextDecoder().decode(record.ciphertext).includes(config.api_key),false);
  assert.deepEqual(await vault.load(),config);
  await assert.rejects(webcrypto.subtle.exportKey('raw',record.key));
});
test('turning off removes ciphertext and encryption key',async()=>{
  const {vault,storage}=fixture();await vault.save(config);await vault.clear();
  assert.equal(await storage.read(),null);assert.equal(await vault.load(),null);
});
test('tampered ciphertext fails closed',async()=>{
  const {vault,storage}=fixture();await vault.save(config);
  const record=await storage.read();new Uint8Array(record.ciphertext)[0]^=1;
  await assert.rejects(vault.load());
});
test('a mismatched encryption key cannot restore settings',async()=>{
  const {vault,storage}=fixture();await vault.save(config);
  (await storage.read()).key=await webcrypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
  await assert.rejects(vault.load());
});
test('replacement saves one consistent record and clear works without WebCrypto',async()=>{
  const {vault,storage}=fixture();await vault.save(config);
  const next={...config,base_url:'https://other.example/v1',api_key:'other-dummy-key'};
  await vault.save(next);assert.deepEqual(await vault.load(),next);
  const unsupported=createDeviceVault(storage,{});
  await assert.rejects(unsupported.save(config));
  await unsupported.clear();assert.equal(await vault.load(),null);
});
