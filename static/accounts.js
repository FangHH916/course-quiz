'use strict';
function emailAccount(mode='login'){
  const user=state.account.user;
  if(!state.account.configured){
    baseModal(t('邮箱账号','Email account'),t('让学习记录跟着你走。','Keep your learning with you.'),`<div class="modal-hint">${t('邮箱服务尚未连接。管理员完成配置后，可注册、验证邮箱并同步课程资料和成绩。当前仍可使用浏览器工作区。','Email accounts are not connected yet. Once configured, you can register, verify your email, and sync materials and results. Your browser workspace remains available.')}</div>`,`<button class="button button-primary" data-action="close-modal">${t('知道了','Done')}</button>`);return;
  }
  if(user?.verified){
    baseModal(t('我的账号','Your account'),e(user.email),`<div class="account-summary"><span class="account-verified">${icon('check')}${t('邮箱已验证','Email verified')}</span><p>${t('课程资料、测验和已提交成绩已加密同步到账号。使用另一台设备登录同一邮箱即可找回。','Materials, quizzes, and submitted results sync to your account as encrypted data. Sign in with the same email on another device to restore them.')}</p><p>${t('API Key 默认不保存，刷新或退出后需重填。','API keys are not saved by default. Re-enter your key after refreshing or signing out.')}</p>${state.syncWarning?`<p class="modal-error">${e(state.syncWarning)}</p>`:''}</div>`,`<button class="button button-white" id="account-sync">${t('重新同步','Sync now')}</button><button class="button button-white" id="account-signout">${t('退出登录','Sign out')}</button>`);
    $('#account-sync').addEventListener('click',async()=>{const b=$('#account-sync');b.disabled=true;try{await refresh();renderHeader();if(state.syncWarning)modalError(state.syncWarning);else toast(t('账号同步已完成。','Account synced.'));}catch(err){modalError(err.message);}finally{b.disabled=false;}});
    $('#account-signout').addEventListener('click',async()=>{
      if(state.syncWarning){modalError(t('还有记录尚未同步，请先重试同步后再退出，以免记录丢失。','Some records have not synced yet. Retry syncing before signing out to avoid data loss.'));return;}
      const b=$('#account-signout');b.disabled=true;try{await api('/api/account/logout',{});state.history.forEach(q=>{try{localStorage.removeItem(`shizhi-draft-${q.id}`);}catch{}});state.api.api_key='';state.requirements='';save('shizhi-prompt','');state.quiz=null;state.answers={};state.courseId='';state.historyCourse='';await refresh();$('#modal').close();go('workspace');toast(t('已退出登录。','Signed out.'));}catch(err){modalError(err.message);b.disabled=false;}
    });return;
  }
  if(user&&!user.verified&&mode!=='login-again'){
    baseModal(t('验证你的邮箱','Verify your email'),e(user.email),`<div class="modal-hint">${t('请在邮箱中打开验证邮件并点击验证链接，然后返回这里继续。垃圾邮件文件夹也可以检查一下。验证完成后，当前访客资料会转入此账号。','Open the verification email and follow its link, then return here. Check your spam folder too. Once verified, this browser’s guest materials will move into your account.')}</div>`,`<button class="text-button" id="account-switch">${t('换个邮箱','Use another email')}</button><button class="button button-white" id="account-resend">${t('重发验证邮件','Resend email')}</button><button class="button button-primary" id="account-verified">${t('我已验证，继续','I verified my email')}</button>`);
    $('#account-switch').addEventListener('click',async()=>{try{await api('/api/account/logout',{});await refresh();emailAccount('login-again');}catch(err){modalError(err.message);}});
    $('#account-resend').addEventListener('click',async()=>{const b=$('#account-resend');b.disabled=true;try{await api('/api/account/resend',{});toast(t('验证邮件已发送，请稍候查看邮箱。','Verification email sent. Check your inbox shortly.'));}catch(err){modalError(err.message);}finally{b.disabled=false;}});
    $('#account-verified').addEventListener('click',async()=>{const b=$('#account-verified');b.disabled=true;try{const result=await api('/api/account/check-verification',{});if(!result.user?.verified){modalError(t('邮箱尚未完成验证，请先点击邮件中的验证链接。','Your email is not verified yet. Follow the link in the verification email first.'));return;}await finishAccountLogin();}catch(err){modalError(err.message);}finally{if(b.isConnected)b.disabled=false;}});return;
  }
  const register=mode==='register',reset=mode==='reset';
  baseModal(reset?t('找回密码','Reset your password'):register?t('注册并绑定邮箱','Create your email account'):t('邮箱登录','Sign in with email'),reset?t('向邮箱发送密码重置链接。','Send a password reset link to your inbox.'):t('验证后同步资料和成绩，API Key 默认不保存。','Sync materials and results after verifying. API keys are not saved by default.'),`<div class="account-tabs" ${reset?'hidden':''}><button id="account-login-tab" class="${register?'':'active'}">${t('登录','Sign in')}</button><button id="account-register-tab" class="${register?'active':''}">${t('注册','Register')}</button></div><form id="account-form"><label class="field-label" for="account-email">${t('邮箱地址','Email address')}</label><input id="account-email" name="email" type="email" autocomplete="email" maxlength="254" required placeholder="you@example.com" value="${e(user?.email||'')}">${reset?'':`<label class="field-label" for="account-password">${t('密码','Password')}</label><input id="account-password" name="password" type="password" autocomplete="${register?'new-password':'current-password'}" minlength="${register?12:1}" maxlength="128" required placeholder="${register?t('至少 12 个字符','At least 12 characters'):t('输入密码','Your password')}">${register?`<label class="field-label" for="account-confirm">${t('确认密码','Confirm password')}</label><input id="account-confirm" type="password" autocomplete="new-password" required maxlength="128">`:''}`}</form>${register?`<div class="account-privacy">${t('邮箱与认证信息由 Firebase Authentication 处理。学习记录加密保存到账号，只有验证过的账号可访问自己的记录。','Firebase Authentication handles your email and sign-in details. Learning records are encrypted and accessible only to their verified owner.')}</div>`:''}`,`<button class="text-button" id="account-help">${reset?t('返回登录','Back to sign in'):t('忘记密码？','Forgot password?')}</button><button class="button button-primary" id="account-submit">${reset?t('发送重置邮件','Send reset email'):register?t('注册并发送验证邮件','Register and send verification'):t('登录','Sign in')}</button>`);
  if(!reset){$('#account-login-tab').addEventListener('click',()=>emailAccount('login'));$('#account-register-tab').addEventListener('click',()=>emailAccount('register'));}
  $('#account-help').addEventListener('click',()=>emailAccount(reset?'login':'reset'));
  const submit=async()=>{
    const form=$('#account-form');if(!form.reportValidity())return;if(register&&$('#account-password').value!==$('#account-confirm').value){modalError(t('两次输入的密码不一致。','The passwords do not match.'));return;}
    const b=$('#account-submit');b.disabled=true;
    try{
      const data={email:$('#account-email').value.trim()};if(!reset)data.password=$('#account-password').value;
      const result=await api('/api/account/'+(reset?'reset-password':register?'register':'login'),data);
      if(reset){$('#modal').close();toast(t('如果该邮箱可接收重置邮件，你会收到一封邮件，请同时检查垃圾邮件。','If a reset email can be sent to that address, it will arrive shortly. Check your spam folder too.'));return;}
      if(result.user?.verified){await finishAccountLogin();return;}
      await refresh();renderHeader();emailAccount();if(register&&result.verification_sent===false)modalError(t('账号已创建，但验证邮件暂未发出，请稍后重试发送。','Your account was created, but the verification email could not be sent. Retry shortly.'));
    }catch(err){modalError(err.message);}finally{if(b.isConnected)b.disabled=false;}
  };
  $('#account-submit').addEventListener('click',submit);$('#account-form').addEventListener('submit',ev=>{ev.preventDefault();if(!$('#account-submit').disabled)submit();});
}
async function finishAccountLogin(){
  const oldStorageId=state.storageId;
  state.quiz=null;state.answers={};state.historyCourse='';state.courseId='';state.api.api_key='';
  await refresh();
  if(oldStorageId&&oldStorageId!==state.storageId){try{await window.ShizhiBackup.remove(oldStorageId);}catch{}}
  $('#modal').close();go('workspace');toast(t('邮箱已绑定，学习记录已转入账号。','Signed in. Your learning records are now linked to your email.'));
}
