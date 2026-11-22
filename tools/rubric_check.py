"""Reference scorer for STANDARDS v2 rubrics; used to verify every worked example."""
import math
def band(v, edges, higher=True):
    # edges: thresholds for 4,3,2,1 ; value on edge goes to better band
    pts=[4,3,2,1]
    for p,e in zip(pts,edges):
        if (v>=e if higher else v<=e): return p
    return 0
def rdown(x): return math.floor(x*2)/2
def vi01(credits_floor, credits_ceil, n, penalty=0):
    f=band(100*credits_floor/n,[90,75,60,40]); c=band(100*credits_ceil/n,[90,75,60,40])
    return max(f-penalty,0), max(c-penalty,0), 100*credits_floor/n, 100*credits_ceil/n
def score(crit):  # crit: name -> (weight, pf, pc)
    F=sum(w*pf/4 for w,pf,pc in crit.values()); C=sum(w*pc/4 for w,pf,pc in crit.values()); return round(F,2), round(C,2)
def rule(F,C):
    if C<50: return 'negative'
    if F>=75: return 'positive'
    if F>=50: return 'positive with conditions'
    return 'hold'

print('=== R1 Company C ===')
s1f=band(100*6/7,[90,75,50,25]); s1c=band(100,[90,75,50,25])
s4=rdown((3+3+3)/3)
s8=rdown((4+2)/2)
tc01=band(100*(1+0.75+0.5)/3,[90,75,60,40])
s9f=rdown((0+tc01)/2); s9c=rdown((4+tc01)/2)
R1={'S1':(15,s1f,s1c),'S2':(15,3,3),'S3':(10,4,4),'S4':(15,s4,s4),'S5':(5,4,4),'S6':(10,3,3),'S7':(10,2,2),'S8':(10,s8,s8),'S9':(10,s9f,s9c)}
print({k:v for k,v in R1.items()}, 'TC01',tc01); F,C=score(R1); print('floor',F,'ceil',C)
cov=15*6/7+10*0.5+15+10+15+5+10+10+10; print('coverage',round(cov,2))

print('=== R2 Company C (target) ===')
c1f,c1c,rf,rc=vi01(10+1.5+0.5,10+1.5+0.5+1,14,penalty=1); print('C1',c1f,c1c,round(rf,1),round(rc,1))
lf05=band(100*(4+4*0.75+0.5)/9,[90,75,60,40]); lf=[3,3,4,4,lf05,3,3]; lfc=rdown(sum(lf)/7); print('LF',lf,round(sum(lf)/7,2),'->',lfc)
fp02=(62+72.7+50+33/48*100)/4; print('FP02 at check',round(fp02,1))
rg=rdown((band(fp02,[60,40,25,10])+2)/2)
tc01f=band(100*(0.75+1+0.5+0+0.5)/5,[90,75,60,40]); tc01c=band(100*(0.75+1+0.5+1+0.5)/5,[90,75,60,40]); tc02=band(3,[12,8,5,2])
c11f=rdown((tc01f+tc02)/2); c11c=rdown((tc01c+tc02)/2); print('TC01',tc01f,tc01c,'TC02',tc02,'C11',c11f,c11c)
R2={'C1':(20,c1f,c1c),'C2':(20,3,3),'C3':(10,3,3),'C4':(10,3,3),'C5':(5,3,3),'C6':(5,4,4),'C7':(5,band(85,[90,75,50,25]),4),'C8':(0,0,0),'C9':(15,lfc,lfc),'C10':(5,rg,rg),'C11':(5,c11f,c11c)}
F,C=score(R2); print(R2); print('floor',F,'ceil',C,rule(F,C))
# what-if: contract extract + tech evidence
c1f2,_,r2,_=vi01(11+1.5+0.5,0,14,penalty=1)
tc01f2=band(100*(0.75+1+1+1+0.5)/5,[90,75,60,40]); c11f2=rdown((tc01f2+tc02)/2)
R2b=dict(R2); R2b['C1']=(20,c1f2,c1c); R2b['C11']=(5,c11f2,c11c); F2,_=score(R2b); print('after contract+tech evidence: C1',c1f2,'C11',c11f2,'floor',F2,rule(F2,100))
R2c=dict(R2); R2c['C1']=(20,c1f2,c1c); F3,_=score(R2c); print('after contract only floor',F3)
cov=20*13/14+20+10+10+5+5+5*0.85+15+5+5*5/6; print('coverage',round(cov,2))
# health grade
pill=[3, (2+3)/2 if False else 2.5, 2.5, 3, 2, 2.5, 4]; print('grade mean',round(sum(pill)/7,3))

print('=== R2 vendor worked example ===')
c1f,c1c,rf,rc=vi01(8+0.75+0.5,8+0.75+0.5+2,12); c8f,c8c,_,_=vi01(3+0.5,3+0.5+1,5)
V={'C1':(20,c1f,c1c),'C2':(15,3,3),'C3':(5,3,3),'C4':(0,0,0),'C5':(10,3,3),'C6':(10,4,4),'C7':(5,band(70,[90,75,50,25]),4),'C8':(15,c8f,c8c),'C9':(5,3,3),'C10':(10,3,3),'C11':(5,3,3)}
F,C=score(V); print(V, round(rf,1), round(rc,1)); print('floor',F,'ceil',C,rule(F,C))
c8f2,_,_,_=vi01(4,0,5); V2=dict(V); V2['C8']=(15,c8f2,c8c); print('after RC floor',score(V2)[0])
cov=20*10/12+15+5+10+10+5*0.7+15*0.8+5+10+5; print('coverage',round(cov,2))
print('weights target',sum(w for w,_,_ in R2.values()),'vendor',sum(w for w,_,_ in V.values()),'R1',sum(w for w,_,_ in R1.values()))
