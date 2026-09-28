import {test,expect} from '@playwright/test';
test('authenticated workbench lists real fixture projects',async({page})=>{
 const token=process.env.TF_REVIEWER_TOKEN;
 if (!token) throw new Error('TF_REVIEWER_TOKEN is required: E2E cannot silently skip');
 await page.goto('/');await page.getByLabel('访问令牌').fill(token!);await page.getByRole('button',{name:'连接工作区'}).click();
 await expect(page.getByRole('heading',{name:'新建验证任务'})).toBeVisible();
 await page.getByRole('link',{name:'▦ 样例项目'}).click();
 await expect(page.getByRole('heading',{name:'删除后分页越界'})).toBeVisible();
});
