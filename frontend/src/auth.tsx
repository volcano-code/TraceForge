import {createContext,useContext,useState,type ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {api} from './api';
import {createIntentManager,type IntentManager} from '../../src/traceforge/static/create-intent.mjs';
import type {Meta} from './types';
interface Auth {intents:IntentManager;token:string;meta:Meta|null;login:(token:string)=>Promise<void>;logout:()=>void}
const Context=createContext<Auth|null>(null);
export function AuthProvider({children}:{children:ReactNode}){
 const [intents]=useState(()=>createIntentManager());
 const [token,setToken]=useState('');const[meta,setMeta]=useState<Meta|null>(null);const cache=useQueryClient();
 async function login(value:string){const metadata=await api<Meta>(value,'/meta');intents.resetSession();cache.clear();setToken(value);setMeta(metadata);}
 function logout(){intents.resetSession();setToken('');setMeta(null);cache.clear();}
 return <Context.Provider value={{token,meta,login,logout,intents}}>{children}</Context.Provider>;
}
export function useAuth(){const value=useContext(Context);if(!value)throw new Error('AuthProvider missing');return value;}
