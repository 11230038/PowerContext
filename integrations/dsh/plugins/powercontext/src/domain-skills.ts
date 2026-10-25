/*
 * Copyright (c) 2026 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { readSkillResource, REFERENCE_RESOURCE_BASE } from './skill-body.ts'

export const DOMAIN_SKILLS = [
  { name: 'powercontext-memory', description: 'PowerContext Memory search, inventory, save and correction (搜索记忆、盘点、记住、纠正).', source: 'runtime', resourceBase: REFERENCE_RESOURCE_BASE, content: readSkillResource('references/scope-memory.md') },
  { name: 'powercontext-handoff', description: 'PowerContext temporary handoff, durable milestone and continuation (临时交接、持久里程碑、接续).', source: 'runtime', resourceBase: REFERENCE_RESOURCE_BASE, content: readSkillResource('references/work-handoff.md') },
  { name: 'powercontext-review', description: 'PowerContext candidate inspection, review, Experience and Skills (审查候选、经验、技能).', source: 'runtime', resourceBase: REFERENCE_RESOURCE_BASE, content: readSkillResource('references/review-publication.md') + '\n' + readSkillResource('references/experience-skills.md') },
]
