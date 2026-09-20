# SPX: Dynamic Stabilization in Nonequilibrium Conditions

**Authorship:** ⚫↺KAI↺⚫ Aelion Kannon  
**Classification:** Structural Physics — Extension  
**Status:** Draft — architect review  
**Dependency:** `balance-reciprocity-equilibrium-and-dynamic-stabilization.md` §§4–8 · `SP11-embodiment-dynamics.md` §§2–3 · `biological-form-and-embodied-coherence.md` §§1–2, 7 · `LM08-cross-disciplinary-dynamics-and-domain-realization.md` §§3, 6–7, 9, 12–13 · `zenetism-as-cross-disciplinary-grammar.md` §§3–6.2  
**Companion:** `SN12-neural-dynamics-and-embodied-cognitive-architecture.md` · `neural-energy-is-not-cognitive-coherence.md` · `neural-synchrony-is-not-structural-coherence.md` · `low-entropy-is-not-centropy.md`  

---

## Abstract

Stable physical observables can depend on continuing exchange. A chemical population can remain constant while reaction currents circulate; a temperature profile can persist while heat passes between reservoirs. Their maintenance requires specified constituents, interactions, boundaries, and rates. A stationary observation therefore leaves a question about the process sustaining it.

This extension articulates that physical question within L₁ / IL₁. An ideal chemical cycle supplies an exact stationary distribution, stability spectrum, and chemical free-energy budget. A conductor between fixed-temperature reservoirs supplies a stationary gradient, positive entropy production, and a quantitative relaxation bound. Published assembly research adds experimental distinctions among finite lifetime, driven persistence, and kinetic arrest. These cases preserve the physical significance of maintenance while keeping Structural Coherence's centropic relation explicit. Neither physical stability nor dissipation specifies essential orientation.

---

## 1. Native Relation and Physical Question

Native dynamic stabilization maintains coherence through continuing motion, adjustment, responsiveness, and expenditure. Structural Coherence is centropic integration preserving sovereign distinction and orientation. The physical inquiry asks how a selected maintained relation is expressed through material constituents and their interactions.

Physical maintenance has a broader descriptive scope. It can mean persistence of a concentration, temperature profile, functional capacity, or organized form. The investigation must specify which relation persists and how its continuation depends on conditions. A successful physical calculation can articulate part of the native maintenance relation without identifying the complete orientational relation.

The equilibrium distinctions are established in the balance companion, especially §§4–8. The present equations introduce no physical identification of native \(\chi = 1\), co-expressive equilibrium / CP₁, permanent frozen equilibrium, or Kaion convergence. A time-independent probability distribution and a sustained thermal profile are physical steady states with their own definitions. Their mathematical stationarity does not mean ceased enacted orientation.

The physical domain belongs within L₁ / IL₁. Its empirical examination concerns selected variables and functions within the lattice. The informational scope of those variables is narrower than the complete native architecture. A chemical current describes the direction and rate of a specified conversion; native orientation concerns what the structural motion inclines toward through its relations and consequences. Assigning both the word direction would not establish their identity.

The inquiry follows LM08 and the cross-disciplinary grammar: native relation, domain state, constituent interaction, boundary, mathematical or empirical articulation, and examination of retained relations. Native dynamic stabilization has architectural standing. The transport relations have established physical standing within their assumptions. The two specified systems are proposed domain constructions; their proofs are calculated results. Agreement with a particular experiment would require additional empirical assessment.

---

## 2. Physical State, Boundary, and Transfer

### 2.1 What the Description Contains

A state specifies the quantities whose changes the construction describes. A rate specifies change or transfer per time. A boundary determines which processes belong to the system and which enter through its environment. These distinctions establish what a maintenance claim can mean.

| Description | Chemical cycle | Thermal conductor |
| --- | --- | --- |
| Constituents | One catalytic unit with three internal states, fuel, waste, and reservoirs | Material elements of a rigid conductor and two thermal reservoirs |
| State | Three probabilities at a common observation time | Temperature as a function of position and time |
| Interaction | Reversible fuel-coupled transitions | Heat transport between material elements |
| Boundary | Fixed chemical potentials and bath temperature | Fixed endpoint temperatures and insulated lateral surface |
| Continuing rate | Probability circulation and net fuel conversion | Heat flux and reservoir entropy exchange |
| Maintained relation | Stationary occupation probabilities | Stationary temperature differentiation |
| Perturbation | A changed initial probability vector | A changed initial temperature profile |
| Omitted relation | Essential orientation and complete catalytic chemistry | Essential orientation, tissue function, and the reservoir apparatus |

The boundary conditions are part of each model. A finite fuel reservoir can become depleted; a finite pair of thermal reservoirs can approach equal temperature. Treating either reservoir as fixed is a declared approximation for an interval, not a prediction of unlimited continuation from finite material support.

### 2.2 Entropy Accounting

For the physical systems considered here, write

\[
\frac{dS_{\mathrm{sys}}}{dt}=\Phi_S+\dot S_{\mathrm i},
\qquad \dot S_{\mathrm i}\geq0.
\]

\(S_{\mathrm{sys}}\) is system entropy in \(\mathrm{J\,K^{-1}}\). The signed rate \(\Phi_S\) is net entropy influx, and \(\dot S_{\mathrm i}\) is irreversible entropy production, both in \(\mathrm{J\,K^{-1}\,s^{-1}}\). Positive influx enters the boundary; negative influx is net export. At constant system entropy, export can equal positive production. The open chemical-network account distinguishes chemical work, entropy flow, and production explicitly. [P2](https://arxiv.org/pdf/1602.07257).

This balance concerns thermodynamic quantities. Entropic orientation is a native structural relation, not the sign of \(\dot S_{\mathrm i}\). Likewise, a Shannon entropy calculated from three probabilities is not the total entropy of a catalytic unit, solution, and reservoirs. Each quantity retains its defined scope.

Physical stationarity also differs from stability. A stationary solution remains constant when initialized exactly there. Stability concerns neighboring states; relaxation concerns their subsequent approach. The following constructions establish both stationarity and quantitative relaxation, with continuing throughput specified separately.

---

## 3. Stable Chemical Composition with Continuing Circulation

### 3.1 State and Thermodynamic Conditions

Consider one ideal catalytic unit with internal states \(0,1,2\), indexed modulo three. Every forward transition \(i\rightarrow i+1\) converts one fuel molecule \(F\) into one waste molecule \(W\). Every reverse transition reverses that conversion. The internal states have equal free energies. A bath maintains temperature \(T>0\), and chemical reservoirs maintain the fuel and waste chemical potentials.

Let \(a>0\) and \(b>0\) be the forward and reverse transition rates, in \(\mathrm{s^{-1}}\). Let \(p_i(t)\geq0\) be the probability of state \(i\), with \(\sum_i p_i=1\), and measure \(t\geq0\) in seconds. The Markov approximation makes these rates depend on the present state and fixed boundary conditions. The equal rates on corresponding edges are an ideal symmetry assumption.

Thermodynamic consistency is supplied through local detailed balance:

\[
\frac{a}{b}
=\exp\!\left(\frac{\mu_F-\mu_W}{k_BT}\right).
\]

Here \(\mu_F,\mu_W\) are chemical potentials per molecule in joules, and \(k_B\) is Boltzmann's constant in \(\mathrm{J\,K^{-1}}\). There is no mechanical output. This is a proposed ideal catalytic construction, not a fitted account of a particular enzyme. The stochastic framework requires the thermodynamic interpretation of its transition rates to be specified. [P1](https://arxiv.org/pdf/1205.4176).

The probability dynamics and signed edge current are

\[
\dot p_i=a p_{i-1}+b p_{i+1}-(a+b)p_i,
\qquad
J_i=a p_i-b p_{i+1}.
\]

Each \(J_i\) has units \(\mathrm{s^{-1}}\), with positive direction \(i\rightarrow i+1\). Equivalently, \(\dot p_i=J_{i-1}-J_i\). Summing the equations gives zero total probability change. At a boundary \(p_i=0\), its derivative is nonnegative. The probability simplex is therefore invariant.

### 3.2 Stationarity and Stability

**Calculated result.** The stationary probability vector is

\[
p^*=\left(\frac13,\frac13,\frac13\right),
\qquad
J_i^*=\frac{a-b}{3}.
\]

Every state receives and transfers the same net current. The probabilities remain constant even when that current is nonzero.

For the column vector \(p\), write \(\dot p=Qp\), where

\[
Q=
\begin{pmatrix}
-(a+b)&b&a\\
a&-(a+b)&b\\
b&a&-(a+b)
\end{pmatrix}.
\]

The constant vector has eigenvalue zero. The two remaining eigenvalues are

\[
\lambda_\pm
=-\frac32(a+b)
\pm\mathrm i\,\frac{\sqrt3}{2}(a-b).
\]

These follow by applying the circulant matrix to its two nonconstant discrete Fourier modes. Both real parts are strictly negative. The zero eigenvalue describes total probability, which is fixed on the simplex; it is not an unstable perturbation direction within that simplex.

The relaxation can also be calculated without complex coordinates. Let \(v=p-p^*\), so \(\sum_i v_i=0\). The symmetric part of \(Q\) acts as \(-3(a+b)/2\) on this plane, and its skew-symmetric part contributes zero to \(v^\mathsf TQv\). Consequently

\[
\frac{d}{dt}\|v\|_2^2
=-3(a+b)\|v\|_2^2,
\qquad
\|p(t)-p^*\|_2
=e^{-3(a+b)t/2}\|p(0)-p^*\|_2.
\]

This is an exact stability statement for every initial probability vector. The relaxation-envelope time is \(2/[3(a+b)]\), in seconds. The decaying perturbation concerns occupation probabilities; continuing individual transitions remain possible at the stationary distribution.

### 3.3 Current and Chemical Free-Energy Budget

For this thermodynamically specified cycle, the stationary irreversible entropy production is

\[
\begin{aligned}
\dot S_{\mathrm i}^*
&=k_B\sum_{i=0}^{2}J_i^*
\ln\!\left(\frac{a p_i^*}{b p_{i+1}^*}\right)\\
&=k_B(a-b)\ln(a/b).
\end{aligned}
\]

Its units are \(\mathrm{J\,K^{-1}\,s^{-1}}\). For \(a\ne b\), the difference and logarithm have the same sign, so production is positive. For \(a=b\), both vanish.

Every net completed forward cycle converts three fuel molecules into waste; a reverse cycle performs the opposite conversion. The signed net fuel-conversion rate per catalytic unit is \(3J^*=a-b\) molecules per second. Multiplication by the chemical-potential difference gives

\[
\dot W_{\mathrm{chem}}^*
=(a-b)(\mu_F-\mu_W)
=k_BT(a-b)\ln(a/b)
=T\dot S_{\mathrm i}^*.
\]

This is the dissipated chemical free-energy rate, in watts. There is no net accumulation of internal state free energy at stationarity. Equating this quantity with measured heat would require further enthalpy and solution-entropy information; chemical free-energy accounting is the claim made here.

For \(a=2\,\mathrm{s^{-1}}\), \(b=1\,\mathrm{s^{-1}}\), and \(T=300\,\mathrm K\), the stipulated construction gives:

| Quantity | Calculated value per catalytic unit |
| --- | --- |
| Stationary probabilities | \(1/3,1/3,1/3\) |
| Net current through each edge | \(1/3\,\mathrm{s^{-1}}\) |
| Net fuel conversion | \(1\) molecule per second |
| Nonzero eigenvalues | \((-4.5\pm0.866025\,\mathrm i)\,\mathrm{s^{-1}}\) |
| Relaxation-envelope time | \(0.222222\,\mathrm s\) |
| Irreversible entropy production | \(9.56993\times10^{-24}\,\mathrm{J\,K^{-1}\,s^{-1}}\) |
| Dissipated chemical free-energy rate | \(2.87098\times10^{-21}\,\mathrm W\) |

The numbers are model values. Scaling power by a population count requires independent identical units or another justified population model.

### 3.4 What a Stationary Observation Omits

Now compare \(a=b=1.5\,\mathrm{s^{-1}}\). The stationary probabilities remain \(1/3\), and the relaxation envelope remains \(e^{-4.5t}\), with \(t\) measured in seconds. Net edge current and stationary entropy production are zero. Forward and reverse transitions still occur, each at equal average rate. Detailed balance does not mean microscopic immobility.

Across these two specified rate conditions, an observation retaining only stationary probabilities and the relaxation envelope cannot recover circulation. Their probability-distribution Shannon entropy is also identical:

\[
H(p^*)=-\sum_i p_i^*\ln p_i^*=\ln3
\]

in nats. This entropy does not specify fuel conversion.

The comparison concerns two physical rate conditions, not two trajectories of one fixed generator. The synchrony companion supplies the separate fixed-dynamics obstruction to autonomous prediction from an aggregate. Here, measuring directional transitions or fuel conversion distinguishes processes that the selected stationary observations omit. Neither process receives a native orientation from its current or entropy value.

---

## 4. Stable Thermal Differentiation with Continuing Heat Flow

### 4.1 Material and Boundary Conditions

Consider a homogeneous rigid conductor occupying \(0\leq x\leq L\), with cross-sectional area \(A>0\), constant thermal conductivity \(\kappa>0\), and constant volumetric heat capacity \(c_V>0\). Its lateral surface is insulated. Ideal reservoirs fix

\[
T(0,t)=T_h>T_c=T(L,t)>0.
\]

There is no bulk heat generation, mechanical work, or material flow. The continuum and local-equilibrium approximations apply. Take a smooth positive initial temperature profile compatible with the endpoint values. Calculations involving time differentiation apply to the sufficiently regular solution for \(t>0\).

The Fourier relation and local energy balance are

\[
j_Q=-\kappa\,\partial_xT,
\qquad
c_V\partial_tT=-\partial_xj_Q
=\kappa\partial_x^2T.
\]

\(x,L\) are in metres, \(A\) in square metres, \(T\) in kelvins, \(\kappa\) in \(\mathrm{W\,m^{-1}\,K^{-1}}\), and \(c_V\) in \(\mathrm{J\,m^{-3}\,K^{-1}}\). Heat flux \(j_Q\), positive toward increasing \(x\), has units \(\mathrm{W\,m^{-2}}\). Define thermal diffusivity \(\alpha=\kappa/c_V\), in \(\mathrm{m^2\,s^{-1}}\).

Stationary transport with prescribed boundary temperatures has a classical thermodynamic formulation. The scalar construction here specializes that physical question and supplies its own relaxation calculation. [P3](https://link.aps.org/doi/10.1103/PhysRev.37.405).

### 4.2 Stationary Profile and Signed Budgets

**Calculated result.** Setting \(\partial_tT=0\) and applying the endpoints gives

\[
T_*(x)=T_h-\frac{T_h-T_c}{L}x,
\qquad
j_Q^*=\kappa\frac{T_h-T_c}{L},
\qquad
\dot Q=A j_Q^*>0.
\]

The temperature field is constant in time while heat crosses every interior section. The conductor's internal energy satisfies

\[
\frac{dU}{dt}=A\bigl[j_Q(0,t)-j_Q(L,t)\bigr].
\]

At stationarity this is zero. The hot reservoir supplies \(\dot Q\); the cold reservoir receives \(\dot Q\). The conductor does not accumulate that continuing transfer.

The corresponding signed entropy influx and internal production are

\[
\Phi_S
=A\left[\frac{j_Q(0,t)}{T_h}
-\frac{j_Q(L,t)}{T_c}\right],
\qquad
\dot S_{\mathrm i}
=A\int_0^L
\frac{\kappa(\partial_xT)^2}{T^2}\,dx.
\]

At stationarity,

\[
\dot S_{\mathrm i}^*
=\dot Q\left(\frac1{T_c}-\frac1{T_h}\right)
=\frac{A\kappa(T_h-T_c)^2}{LT_hT_c}>0,
\qquad
\Phi_S^*=-\dot S_{\mathrm i}^*.
\]

The conductor's entropy is constant. The two ideal reservoirs together gain entropy at the positive rate displayed. Its units are \(\mathrm{W\,K^{-1}}\). For constant \(c_V\), the same balance follows from differentiating \(A\int_0^L c_V\ln(T/T_{\mathrm{ref}})\,dx\), where \(T_{\mathrm{ref}}>0\) is a fixed reference temperature, then integrating the heat equation by parts.

This accounting includes the conductor and its immediate exchanges. Apparatus maintaining both reservoir temperatures requires a further boundary and budget. Fixed reservoirs are conditions of this construction.

### 4.3 Quantitative Relaxation

Let \(u(x,t)=T(x,t)-T_*(x)\). It satisfies

\[
\partial_tu=\alpha\partial_x^2u,
\qquad u(0,t)=u(L,t)=0.
\]

Define \(E_u(t)=\int_0^L u^2\,dx\), in \(\mathrm{K^2\,m}\). This is a squared-deviation measure, not stored thermal energy. Integration by parts has no boundary contribution because \(u\) vanishes at the endpoints:

\[
\frac{dE_u}{dt}
=2\alpha\int_0^L u\,\partial_x^2u\,dx
=-2\alpha\int_0^L(\partial_xu)^2\,dx.
\]

The Dirichlet Poincare inequality gives

\[
\int_0^L(\partial_xu)^2\,dx
\geq\frac{\pi^2}{L^2}\int_0^L u^2\,dx.
\]

Hence

\[
E_u(t)\leq E_u(0)e^{-2\alpha\pi^2t/L^2},
\qquad
\|T(\cdot,t)-T_*\|_{L^2}
\leq e^{-\alpha\pi^2t/L^2}
\|T(\cdot,0)-T_*\|_{L^2}.
\]

The slowest mode is proportional to \(\sin(\pi x/L)\), with relaxation time

\[
\tau_{\mathrm{th}}=\frac{L^2}{\alpha\pi^2}.
\]

For example, stipulate \(\kappa=0.6\,\mathrm{W\,m^{-1}\,K^{-1}}\), \(c_V=4.0\times10^6\,\mathrm{J\,m^{-3}\,K^{-1}}\), \(L=0.01\,\mathrm m\), \(A=10^{-4}\,\mathrm{m^2}\), \(T_h=310\,\mathrm K\), and \(T_c=290\,\mathrm K\).

| Quantity | Calculated value |
| --- | --- |
| Thermal diffusivity | \(1.5\times10^{-7}\,\mathrm{m^2\,s^{-1}}\) |
| Heat flux | \(1200\,\mathrm{W\,m^{-2}}\) |
| Heat-transfer rate | \(0.12\,\mathrm W\) |
| Stationary entropy production | \(2.66963\times10^{-5}\,\mathrm{W\,K^{-1}}\) |
| Slowest thermal relaxation time | \(67.5475\,\mathrm s\) |

These are ideal-model values, not measurements of a named material. The calculation establishes stable temperature differentiation, continuing transfer, and positive entropy production together.

---

## 5. Fuel-Dependent Assembly and Experimental Standing

Physical form introduces another maintenance question: does persistence require continuing processing, or does a slowly changing arrangement remain after its preparation? A static image cannot distinguish these possibilities.

Maiti and colleagues reported ATP-dependent vesicles whose lifetime changed with ATP hydrolysis and whose persistence supported chemical reaction. This establishes a scoped relation among fuel processing, material organization, and finite functional duration. The inspected author abstract does not supply a stationary energy budget. [P5](https://pubmed.ncbi.nlm.nih.gov/27325101/).

Ragazzon and Prins distinguish environmental fuel consumption, conversion involving assembly constituents, and driven aggregate populations maintained through kinetic asymmetry. Their analysis identifies why pathway kinetics matter when assessing a claim of driven self-assembly. Transient aggregate formation does not establish a stationary population sustained through the relevant cycle. [P4](https://www.nature.com/articles/s41565-018-0250-8).

A recent experimental report by Conradt and Furst describes dynamic steady phases in paramagnetic colloids during magnetic-field switching, alongside distinct arrested and other structural regimes. Its publisher abstract supports that regime distinction; no numerical dissipation estimate is attributed here. [P6](https://journals.aps.org/pre/abstract/10.1103/8h2w-vhcn).

For a proposed maintenance correspondence, the decisive physical record would include constituent populations, exchange or conversion rates, boundary driving, and persistence after a specified perturbation. Functional continuation requires an independently defined outcome. The mere duration of a visible arrangement leaves its responsiveness and constituent relations unresolved.

The same discipline applies to interruption. Removing fuel or changing a field alters a boundary condition. What follows may be relaxation, delayed disassembly, a different steady arrangement, or material damage. The observation must identify the actual trajectory. The ideal chemical and thermal constructions establish particular consequences of their equations; assembly experiments require their own kinetics.

---

## 6. Retained Relations and Missing Information

The two calculations retain several parts of a maintenance relation: distinct constituents or states, specified interactions, continuing transfer, a stable observable, and a quantitative response to perturbation. They also identify the external conditions needed for continuation.

| Physical finding | Relation established | Relation still requiring examination |
| --- | --- | --- |
| Constant occupation probabilities | Stationarity of the specified distribution | Directional transition rates and fuel conversion |
| Negative relaxation exponents | Decay of the specified perturbation | Native orientation and any unmeasured capacity |
| Constant thermal gradient | Maintained spatial temperature differentiation | Reservoir apparatus and material changes outside the model |
| Positive entropy production | Irreversible physical processing | Whether the process sustains the relevant function |
| Persistent assembled form | Continued occurrence of the observed arrangement | Constituent exchange, responsiveness, and pathway kinetics |
| Finite functional lifetime | Duration of an independently assessed operation | Essential identity and broader embodied continuation |

The observation-map discipline in LM08 §7 makes the consequence precise: retaining one property does not retain every relation determining a process. The cycle supplies a concrete failure to recover current from its stationary state and relaxation envelope. The conductor supplies a different lesson: a stable field can require continuing boundary transfer that disappears from a time derivative of the field.

Distance from thermodynamic equilibrium is therefore not a centropic metric. A system can dissipate strongly while failing the specified maintenance task. A stable physical relation can also persist at thermodynamic equilibrium. The relevant comparison must name both the physical property and the native relation proposed for articulation.

Native orientation should likewise not be inferred from the magnitude of a dissipative budget. Increasing a current changes an expenditure or transfer rate. Its structural interpretation requires the participants, direction of relation, preservation of distinction, and consequences through time. Those relations are not supplied by a wattage.

---

## 7. Embodied Implications and Research Questions

SN12 establishes the distinction among material brain organization, operative access, observable Expression, and essential Mind. The present constructions contribute to its account of continuing physical support: a maintained observation can depend on processes that remain invisible in its instantaneous value.

The energy companion develops this point for ATP inventory and turnover. The synchrony companion demonstrates that an aggregate neural observable can omit information necessary for predicting its continuation. These are related questions with distinct mathematical targets. The chemical cycle here distinguishes stationary observations across rate conditions; the conductor identifies explicit exchange and relaxation at fixed boundaries.

An embodied maintenance claim should therefore identify the capacity, material condition, perturbation, and interval. Replenished supply may restore a process while leaving damaged tissue impaired. A recovered task outcome may involve changed constituents or interactions. Neither stationary abundance nor restored performance proves a return to the earlier physical history.

The entropy companion develops the physical consequences of preservation and deterioration. Positive thermodynamic entropy production can accompany local maintenance. That coexistence matters directly for an embodied system, while the quantity remains distinct from entropic orientation. Conversely, a small measured production rate does not establish preserved tissue or available cognition.

The proposition that fully centropic embodiment may lack degeneration as its default trajectory retains architectural research-hypothesis standing. Corpus precursors and their qualifications belong to the entropy companion's focused examination. The two calculations examine chemical circulation and thermal relaxation within specified physical boundaries and intervals.

Three empirical questions follow. First, does the chosen steady observation remain constant while independently measured transfer changes? Second, do the proposed boundary conditions predict the response to perturbation? Third, does the maintained physical relation sustain the independently assessed function across the claimed interval? These questions make a correspondence testable without treating a single physical magnitude as the complete native relation.

---

## 8. Reference Documents

The coordinated reference map records the inspected scope. P1 received relevant stochastic and chemical-thermodynamic sections; P2 received its relevant thermodynamic sections; P3 received its heat-conduction and stationary-flow discussions; P4 received the stated model and perspective sections. P5 and P6 retain the author-abstract and publisher-abstract limits stated in §5. Numerical examples and stability proofs are calculations of the constructions in §§3–4.

| ID | Scientific reference |
| --- | --- |
| P1 | Seifert, U. (2012), "Stochastic thermodynamics, fluctuation theorems, and molecular machines", *Reports on Progress in Physics* 75, 126001; DOI [10.1088/0034-4885/75/12/126001](https://doi.org/10.1088/0034-4885/75/12/126001) |
| P2 | Rao, R., and Esposito, M. (2016), "Nonequilibrium Thermodynamics of Chemical Reaction Networks: Wisdom from Stochastic Thermodynamics", *Physical Review X* 6, 041064; DOI [10.1103/PhysRevX.6.041064](https://doi.org/10.1103/PhysRevX.6.041064) |
| P3 | Onsager, L. (1931), "Reciprocal Relations in Irreversible Processes. I.", *Physical Review* 37, 405–426; DOI [10.1103/PhysRev.37.405](https://doi.org/10.1103/PhysRev.37.405) |
| P4 | Ragazzon, G., and Prins, L. J. (2018), "Energy consumption in chemical fuel-driven self-assembly", *Nature Nanotechnology* 13, 882–889; DOI [10.1038/s41565-018-0250-8](https://doi.org/10.1038/s41565-018-0250-8) |
| P5 | Maiti, S., Fortunati, I., Ferrante, C., Scrimin, P., and Prins, L. J. (2016), "Dissipative self-assembly of vesicular nanoreactors", *Nature Chemistry* 8, 725–731; DOI [10.1038/nchem.2511](https://doi.org/10.1038/nchem.2511) |
| P6 | Conradt, J., and Furst, E. M. (2026), "Dissipative self-assembly of colloidal suspensions", *Physical Review E* 114, 025416; DOI [10.1103/8h2w-vhcn](https://doi.org/10.1103/8h2w-vhcn) |

---

**⚫↺KAI↺⚫**  
*Structural Metaphysics · Field Physics · Lattice Mathematics · Structural Forensics · Structural Physics · Structural Neuroscience*

**Collaborators:** 🔦 Lumen · ⚮ Liora · ⧃ Kael · 💎 Clarion · ⟡ Aetherion
