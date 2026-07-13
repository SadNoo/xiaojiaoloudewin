import React, { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import Dashboard from './components/Dashboard';
import AccountList from './components/AccountList';
import OrderList from './components/OrderList';
import CardList from './components/CardList';
import ItemList from './components/ItemList';
import Settings from './components/Settings';
import Keywords from './components/Keywords';
import LicenseGate from './components/LicenseGate';
import { activateLicense, getLicenseStatus, initializeLocalAdmin, login, retryLicenseValidation, verifySession } from './services/api';
import type { LicenseStatus } from './types';
import { ShieldCheck, ArrowRight, Loader2, User, Lock, TerminalSquare, WifiOff } from 'lucide-react';

const App: React.FC = () => {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [checkingLicense, setCheckingLicense] = useState(true);
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null);
  const [licenseLoading, setLicenseLoading] = useState(false);
  const [licenseError, setLicenseError] = useState('');
  const [needsInit, setNeedsInit] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [initEmail, setInitEmail] = useState('');
  const [initPassword, setInitPassword] = useState('');
  const [initPasswordConfirm, setInitPasswordConfirm] = useState('');
  const [initLoading, setInitLoading] = useState(false);
  const [initError, setInitError] = useState('');

  const refreshLocalSession = async () => {
    const res = await verifySession();
    if (res?.initialized === false) {
      setNeedsInit(true);
      setIsLoggedIn(false);
      return;
    }
    setNeedsInit(false);
    setIsLoggedIn(Boolean(res?.authenticated));
  };

  // Authorization must be checked before local user authentication and business UI.
  useEffect(() => {
      const bootstrap = async () => {
        try {
          const currentLicense = await getLicenseStatus();
          setLicenseStatus(currentLicense);
          if (currentLicense.allows_automation) await refreshLocalSession();
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          setLicenseStatus({
            state: 'denied', allows_automation: false,
            message: '无法连接本地授权服务。', initialized: false,
            initialization_error: message,
          });
        } finally {
          setCheckingLicense(false);
          setCheckingAuth(false);
        }
      };
      void bootstrap();

      const handleLogout = () => setIsLoggedIn(false);
      window.addEventListener('auth:logout', handleLogout);
      return () => window.removeEventListener('auth:logout', handleLogout);
  }, []);

  // Reflect heartbeat revocation/expiry in the UI without waiting for a page reload.
  useEffect(() => {
    const timer = window.setInterval(() => {
      getLicenseStatus().then((current) => {
        setLicenseStatus(current);
        if (!current.allows_automation) setIsLoggedIn(false);
      }).catch(() => undefined);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const handleLicenseActivation = async (licenseCode: string) => {
    setLicenseLoading(true);
    setLicenseError('');
    try {
      const result = await activateLicense(licenseCode);
      setLicenseStatus(result);
      if (result.allows_automation) {
        setCheckingAuth(true);
        await refreshLocalSession();
        setCheckingAuth(false);
      } else {
        setLicenseError(result.message || '授权未通过');
      }
    } catch (error) {
      setLicenseError(error instanceof Error ? error.message : String(error));
    } finally {
      setLicenseLoading(false);
    }
  };

  const handleLicenseRetry = async () => {
    setLicenseLoading(true);
    setLicenseError('');
    try {
      const result = await retryLicenseValidation();
      setLicenseStatus(result);
      if (result.allows_automation) await refreshLocalSession();
      else setLicenseError(result.message || '授权仍未通过');
    } catch (error) {
      setLicenseError(error instanceof Error ? error.message : String(error));
    } finally {
      setLicenseLoading(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
      e.preventDefault();
      setLoginLoading(true);
      setLoginError('');
      
      try {
          const res = await login({ username, password });
          if (res.success) {
              setIsLoggedIn(true);
          } else {
              setLoginError(res.message || '登录失败');
          }
      } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          setLoginError(msg || '登录失败');
      } finally {
          setLoginLoading(false);
      }
  };

  const handleLocalAdminInitialize = async (e: React.FormEvent) => {
      e.preventDefault();
      setInitError('');
      if (initPassword.length < 12) {
          setInitError('管理员密码至少需要 12 个字符');
          return;
      }
      if (initPassword !== initPasswordConfirm) {
          setInitError('两次输入的密码不一致');
          return;
      }
      setInitLoading(true);
      try {
          await initializeLocalAdmin(initEmail.trim(), initPassword);
          const result = await login({ username: 'admin', password: initPassword });
          if (!result.success) throw new Error(result.message || '初始化后的自动登录失败');
          setUsername('admin');
          setNeedsInit(false);
          setIsLoggedIn(true);
          setInitPassword('');
          setInitPasswordConfirm('');
      } catch (error) {
          setInitError(error instanceof Error ? error.message : String(error));
      } finally {
          setInitLoading(false);
      }
  };


  if (checkingLicense || (licenseStatus?.allows_automation && checkingAuth)) {
      return (
          <div className="min-h-screen flex items-center justify-center bg-[#f5f5f7]">
              <Loader2 className="w-8 h-8 text-[#FFE815] animate-spin" />
          </div>
      );
  }

  if (licenseStatus && !licenseStatus.allows_automation) {
    return (
      <LicenseGate
        status={licenseStatus}
        loading={licenseLoading}
        error={licenseError}
        onActivate={handleLicenseActivation}
        onRetry={handleLicenseRetry}
      />
    );
  }

  // Init Screen (system not initialized)
  if (needsInit) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F4F5F7] p-4 relative overflow-hidden font-sans">
        <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] bg-yellow-200/40 rounded-full blur-[120px] animate-pulse"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] bg-blue-200/30 rounded-full blur-[120px] animate-pulse" style={{animationDelay: '2s'}}></div>

        <div className="bg-white/80 backdrop-blur-3xl p-8 md:p-12 rounded-[3rem] shadow-[0_20px_60px_-15px_rgba(0,0,0,0.05)] w-full max-w-xl border border-white relative z-10 animate-fade-in">
          <div className="text-center mb-8">
            <div className="w-24 h-24 bg-[#FFE815] rounded-[2rem] flex items-center justify-center shadow-xl shadow-yellow-200 mx-auto mb-6 transform rotate-[-6deg] transition-all duration-500">
              <TerminalSquare className="w-10 h-10 text-black" />
            </div>
            <h2 className="text-3xl font-extrabold text-gray-900 mb-2 tracking-tight">系统尚未初始化</h2>
            <p className="text-gray-600 font-medium">首次使用请创建仅保存在本机的管理员账号。</p>
          </div>

          <form onSubmit={handleLocalAdminInitialize} className="space-y-4">
            <div>
              <label className="block text-sm font-bold text-gray-700 mb-2">管理员账号</label>
              <input value="admin" disabled className="w-full ios-input px-5 h-14 rounded-2xl bg-gray-100 text-gray-500" />
            </div>
            <div>
              <label className="block text-sm font-bold text-gray-700 mb-2">管理员邮箱</label>
              <input type="email" required value={initEmail} onChange={e => setInitEmail(e.target.value)} placeholder="用于标识本地管理员" className="w-full ios-input px-5 h-14 rounded-2xl" />
            </div>
            <div>
              <label className="block text-sm font-bold text-gray-700 mb-2">管理员密码</label>
              <input type="password" required minLength={12} value={initPassword} onChange={e => setInitPassword(e.target.value)} placeholder="至少 12 个字符" className="w-full ios-input px-5 h-14 rounded-2xl" />
            </div>
            <div>
              <label className="block text-sm font-bold text-gray-700 mb-2">确认密码</label>
              <input type="password" required minLength={12} value={initPasswordConfirm} onChange={e => setInitPasswordConfirm(e.target.value)} placeholder="再次输入密码" className="w-full ios-input px-5 h-14 rounded-2xl" />
            </div>
            {initError && <div className="p-3 rounded-xl bg-red-50 text-red-600 text-sm text-center font-bold">{initError}</div>}
            <button disabled={initLoading} className="w-full ios-btn-primary h-14 rounded-2xl text-lg shadow-xl shadow-yellow-200 flex items-center justify-center gap-2 disabled:opacity-60">
              {initLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <>创建并进入客户端 <ArrowRight className="w-5 h-5" /></>}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-gray-100 text-center">
            <span className="text-xs text-gray-400 font-medium tracking-widest uppercase">Secure Bootstrap</span>
          </div>
        </div>
      </div>
    );
  }

  // Login Screen Component
  if (!isLoggedIn) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F4F5F7] p-4 relative overflow-hidden font-sans">
        {/* Animated Background Blobs */}
        <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] bg-yellow-200/40 rounded-full blur-[120px] animate-pulse"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] bg-blue-200/30 rounded-full blur-[120px] animate-pulse" style={{animationDelay: '2s'}}></div>

        <div className="bg-white/80 backdrop-blur-3xl p-8 md:p-12 rounded-[3rem] shadow-[0_20px_60px_-15px_rgba(0,0,0,0.05)] w-full max-w-lg border border-white relative z-10 animate-fade-in">
          
          {/* Header with Logo */}
          <div className="text-center mb-10">
             <div className="w-24 h-24 bg-[#FFE815] rounded-[2rem] flex items-center justify-center shadow-xl shadow-yellow-200 mx-auto mb-6 transform rotate-[-6deg] hover:rotate-0 transition-all duration-500 cursor-pointer group">
                <span className="text-black font-extrabold text-5xl group-hover:scale-110 transition-transform">闲</span>
             </div>
             <h2 className="text-3xl font-extrabold text-gray-900 mb-2 tracking-tight">欢迎回来</h2>
             <p className="text-gray-500 font-medium">闲鱼智能自动发货与管家系统</p>
          </div>
          
          <form onSubmit={handleLogin} className="space-y-5">
            <div className="space-y-4">
                <div className="relative group">
                    <User className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-black transition-colors" />
                    <input 
                        type="text" 
                        placeholder="管理员账号" 
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        className="w-full ios-input pl-14 pr-6 py-4.5 rounded-2xl text-base h-14"
                    />
                </div>
                <div className="relative group">
                    <Lock className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-black transition-colors" />
                    <input 
                        type="password" 
                        placeholder="密码" 
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        className="w-full ios-input pl-14 pr-6 py-4.5 rounded-2xl text-base h-14"
                    />
                </div>
            </div>
            
            {loginError && (
                <div className="p-3 rounded-xl bg-red-50 text-red-500 text-sm text-center font-bold flex items-center justify-center gap-2">
                    <ShieldCheck className="w-4 h-4" /> {loginError}
                </div>
            )}

            <button 
              type="submit" 
              disabled={loginLoading}
              className="w-full ios-btn-primary h-14 rounded-2xl text-lg shadow-xl shadow-yellow-200 mt-2 flex items-center justify-center gap-2 group disabled:opacity-70"
            >
              {loginLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <>立即登录 <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" /></>}
            </button>
          </form>
          
          <div className="mt-8 pt-6 border-t border-gray-100">
             <div className="mt-6 text-center">
                 <span className="text-xs text-gray-400 font-medium tracking-widest uppercase">
                    Xianyu Auto-Dispatch Pro v2.5
                 </span>
             </div>
          </div>
        </div>
      </div>
    );
  }

  // Main App Layout
  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard': return <Dashboard />;
      case 'accounts': return <AccountList />;
      case 'orders': return <OrderList />;
      case 'cards': return <CardList />;
      case 'items': return <ItemList />;
      case 'keywords': return <Keywords />;
      case 'settings': return <Settings />;
      default: return <Dashboard />;
    }
  };

  return (
    <div className="flex min-h-screen bg-[#F4F5F7] text-[#111]">
      <Sidebar 
        activeTab={activeTab} 
        setActiveTab={setActiveTab} 
        onLogout={() => {
            setIsLoggedIn(false);
        }}
      />
      
      <main className="flex-1 ml-64 p-8 md:p-12 overflow-y-auto h-screen relative scroll-smooth">
        {/* Subtle background decoration */}
        <div className="fixed top-0 right-0 w-[800px] h-[800px] bg-gradient-to-bl from-yellow-50 to-transparent rounded-full blur-[120px] pointer-events-none -z-10 opacity-60"></div>
        
        <div className="max-w-[1400px] mx-auto pb-10">
            {licenseStatus?.state === 'allowed_offline' && (
              <div className="mb-5 px-5 py-3 rounded-2xl bg-amber-50 border border-amber-100 text-amber-800 flex items-center gap-3 text-sm font-semibold">
                <WifiOff className="w-5 h-5 shrink-0" />
                授权服务器暂时不可达，当前处于离线宽限；请在 {licenseStatus.offline_until ? new Date(licenseStatus.offline_until).toLocaleString('zh-CN') : '宽限结束前'} 恢复联网。
              </div>
            )}
            {renderContent()}
        </div>
      </main>
    </div>
  );
};

export default App;
