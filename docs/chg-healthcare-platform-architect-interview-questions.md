# CHG Healthcare - Platform Architect Interview Questions

## Interview Panel
- **Reed Sandberg** - Hiring Manager
- **Courtney** - Product Manager  
- **Two Principal Engineers** - Technical depth assessors

---

## Round 1: Product & Vision Alignment (Courtney - Product Manager)

### 1. Tell us about yourself and what attracted you to this Platform Architect role at CHG Healthcare.
**What they're looking for:** Career narrative, motivation, alignment with company mission

### 2. How do you approach building platforms for developers versus building features for end customers?
**What they're looking for:** Understanding of internal vs external product thinking, developer empathy

### 3. Describe a time when you had to balance developer experience with security or compliance requirements.
**What they're looking for:** Practical trade-off decisions, stakeholder management

### 4. How do you measure the success of a platform or infrastructure initiative?
**What they're looking for:** Metrics-driven thinking, understanding of developer productivity metrics

### 5. When you're designing a new platform capability, how do you gather requirements from development teams?
**What they're looking for:** Customer discovery skills, collaboration approach

---

## Round 2: Technical Architecture Deep Dive (Principal Engineers)

### Kubernetes & Container Orchestration

#### 6. Walk us through your experience migrating workloads to Kubernetes. What were the biggest challenges?
**What they're looking for:** Real-world K8s experience, problem-solving approach, lessons learned

#### 7. How do you approach multi-tenancy in Kubernetes? What isolation strategies have you implemented?
**What they're looking for:** Security understanding, namespace design, resource quotas, network policies

#### 8. Describe your experience with Kubernetes operators or custom controllers. Have you built any?
**What they're looking for:** Deep K8s knowledge, automation capabilities, Go programming experience

#### 9. How do you handle secrets management in Kubernetes at scale?
**What they're looking for:** Security best practices, tools like Vault/External Secrets, rotation strategies

### Platform Engineering & Developer Experience

#### 10. What does "Internal Developer Platform" mean to you? What components would you include?
**What they're looking for:** Platform engineering philosophy, understanding of golden paths, self-service

#### 11. Describe your experience with infrastructure as code. What tools have you used and why?
**What they're looking for:** Terraform/Pulumi/Crossplane experience, GitOps workflows, versioning strategies

#### 12. How do you approach CI/CD pipeline design for a large organization with multiple teams?
**What they're looking for:** Pipeline architecture, standardization vs flexibility, security scanning integration

#### 13. Tell us about a time you improved deployment frequency or reduced deployment risk. What was your approach?
**What they're looking for:** DORA metrics understanding, progressive delivery, rollback strategies

### Observability & Reliability

#### 14. How do you design observability into platforms from the ground up?
**What they're looking for:** Metrics/logs/traces understanding, tooling choices (Datadog/Prometheus/etc), golden signals

#### 15. Walk us through your approach to incident response and post-mortems for platform issues.
**What they're looking for:** SRE practices, blameless culture, learning from failures

#### 16. How do you balance innovation with reliability when managing production platforms?
**What they're looking for:** Risk management, testing strategies, gradual rollouts

### Cloud & Infrastructure

#### 17. Describe your experience with AWS (or other cloud providers). What services have you architected solutions with?
**What they're looking for:** Cloud depth, cost optimization, networking knowledge, managed services vs self-hosted

#### 18. How do you approach cost optimization in cloud infrastructure?
**What they're looking for:** FinOps practices, right-sizing, spot instances, reserved capacity strategies

#### 19. What's your experience with service mesh technologies? When would you recommend implementing one?
**What they're looking for:** Istio/Linkerd knowledge, understanding of complexity trade-offs

---

## Round 3: Leadership & Collaboration (Reed - Hiring Manager)

### Technical Leadership

#### 20. This is a high-impact IC role, not a management position. How do you lead without direct authority?
**What they're looking for:** Influence skills, technical credibility, collaboration approach

#### 21. Describe a time when you had to advocate for a significant architectural change. How did you build consensus?
**What they're looking for:** Communication skills, stakeholder management, data-driven decision making

#### 22. Tell us about a technical decision you made that didn't work out. What did you learn?
**What they're looking for:** Humility, learning agility, ability to pivot

### Collaboration & Communication

#### 23. How do you work with security and compliance teams while maintaining development velocity?
**What they're looking for:** Shift-left security, partnership mindset, practical security implementation

#### 24. Describe your experience mentoring or upskilling other engineers on platform technologies.
**What they're looking for:** Teaching ability, documentation skills, knowledge sharing culture

#### 25. How do you handle situations where engineering teams resist adopting platform standards or tools?
**What they're looking for:** Empathy, problem discovery, value demonstration, flexibility

### Healthcare Context

#### 26. What interests you about working in healthcare technology specifically?
**What they're looking for:** Mission alignment, understanding of healthcare challenges, regulatory awareness

#### 27. Are you familiar with healthcare compliance requirements like HIPAA? How do they influence infrastructure design?
**What they're looking for:** Compliance awareness, data encryption, audit logging, access controls

---

## Round 4: Your Questions for Them

**Always prepare 5-7 thoughtful questions. Here are examples:**

1. What are the biggest platform engineering challenges CHG is facing in the next 12 months?
2. How does the platform team measure success? What metrics do you track?
3. Can you describe the current Kubernetes footprint - clusters, namespaces, workload types?
4. What does the developer experience look like today? What are the pain points?
5. How does platform engineering interact with security and compliance teams?
6. What's the tech stack for observability and monitoring?
7. How do engineering teams currently deploy applications? What's the approval/release process?
8. What's the mix between building custom platform tooling vs adopting existing open-source/vendor solutions?
9. What does success look like for this role in the first 90 days? First year?
10. What's the team culture like? How do you handle on-call and incident response?

---

## Preparation Tips

### Technical Preparation
- Review your Kubernetes migration project in detail (timelines, workload counts, challenges, wins)
- Prepare specific examples with STAR format (Situation, Task, Action, Result)
- Brush up on: GitOps, service mesh basics, HIPAA compliance basics, FinOps principles
- Be ready to whiteboard or discuss architecture diagrams

### Behavioral Preparation
- Prepare 3-4 strong stories demonstrating: technical leadership, cross-team collaboration, handling failure/learning, innovation vs stability
- Practice your "tell me about yourself" answer (2-3 minutes max)
- Research CHG Healthcare: their products, engineering blog, tech stack mentions

### Red Flags to Avoid
- Speaking negatively about current/past employers
- Being too management-focused vs technical depth
- Not asking questions (shows lack of interest)
- Over-promising on technologies you haven't used deeply

---

## Key Themes to Emphasize

1. **IC Leadership**: You're transitioning away from management because you're passionate about hands-on architecture
2. **Developer Empathy**: Platforms exist to make developers productive
3. **Pragmatism**: Balance innovation with reliability, perfect vs good enough
4. **Healthcare Mission**: Personal connection through your father + excitement about solving workforce challenges
5. **Kubernetes Depth**: Your ECS-to-K8s migration is directly relevant experience

Good luck! 🚀