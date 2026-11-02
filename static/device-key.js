'use strict';
// Independent of course backups. Nothing in this vault is sent to the server for storage.
(function () {
  const context = new TextEncoder().encode('shizhi-device-model-key-v1');
  function createDeviceVault(storage, cryptoApi) {
    return {
      async save(config) {
        if (!cryptoApi?.subtle) throw new Error('Secure browser storage is unavailable');
        if (!config.api_key || !config.base_url || !config.model) throw new Error('Incomplete API settings');
        const key = await cryptoApi.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
        const iv = cryptoApi.getRandomValues(new Uint8Array(12));
        const plaintext = new TextEncoder().encode(JSON.stringify({base_url:config.base_url,model:config.model,api_key:config.api_key}));
        const ciphertext = await cryptoApi.subtle.encrypt({name:'AES-GCM',iv,additionalData:context},key,plaintext);
        await storage.write({version:1,key,iv,ciphertext});
      },
      async load() {
        const record = await storage.read();
        if (!record) return null;
        if (record.version !== 1 || !cryptoApi?.subtle) throw new Error('Invalid device vault');
        const plaintext = await cryptoApi.subtle.decrypt({name:'AES-GCM',iv:record.iv,additionalData:context},record.key,record.ciphertext);
        const config = JSON.parse(new TextDecoder().decode(plaintext));
        if (!['base_url','model','api_key'].every(k=>typeof config[k]==='string'&&config[k])) throw new Error('Invalid saved API settings');
        return {base_url:config.base_url,model:config.model,api_key:config.api_key};
      },
      async clear() { await storage.clear(); }
    };
  }
  function browserStorage() {
    async function database() {
      return new Promise((resolve,reject)=>{
        const request = indexedDB.open('shizhi-device-secrets',1);
        request.onupgradeneeded = ()=>request.result.createObjectStore('vault');
        request.onsuccess = ()=>resolve(request.result);
        request.onerror = ()=>reject(request.error);
        request.onblocked = ()=>reject(new Error('Device vault is blocked'));
      });
    }
    async function transaction(mode, action) {
      const db = await database();
      try {
        return await new Promise((resolve,reject)=>{
          const tx = db.transaction('vault',mode);
          const request = action(tx.objectStore('vault'));
          tx.oncomplete = ()=>resolve(request?.result??null);
          tx.onerror = ()=>reject(tx.error);
          tx.onabort = ()=>reject(tx.error||new Error('Device vault transaction aborted'));
        });
      } finally { db.close(); }
    }
    return {
      read:()=>transaction('readonly',store=>store.get('settings')),
      write:record=>transaction('readwrite',store=>store.put(record,'settings')),
      clear:()=>transaction('readwrite',store=>store.clear())
    };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports={createDeviceVault};
  else window.ShizhiDeviceKey=createDeviceVault(browserStorage(),window.crypto);
})();
