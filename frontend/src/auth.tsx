import {createContext,useContext,useState,type ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {api} from './api';
import type {Meta} from './types';
interface Auth {token:string;meta:Meta|null;login:(token:string)=>Promise<void>;logout:()=>void}
const Context=createContext<Auth|null>(null);
export function AuthProvider({children}:{children:ReactNode}){
 const [token,setToken]=useState('');const[meta,setMeta]=useState<Meta|null>(null);const cache=useQueryClient();
 async function login(value:string){const metadata=await api<Meta>(value,'/meta');cache.clear();setToken(value);setMeta(metadata);}
 function logout(){setToken('');setMeta(null);cache.clear();}
 return <Context.Provider value={{token,meta,login,logout}}>{children}</Context.Provider>;
}
export function useAuth(){const value=useContext(Context);if(!value)throw new Error('AuthProvider missing');return value;}
