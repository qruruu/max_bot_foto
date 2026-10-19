export type DiskFolders = {photo_root:string;training_root:string;spam_root:string;exchange_root:string};
export type DiskFolderSettings = DiskFolders & {version:number};

export function companyFolders(value: string): DiskFolders {
  const name=value.trim();
  return {photo_root:name,training_root:name+'_TRAINING',spam_root:name+'_SPAM',exchange_root:name+'_ARM_EXCHANGE'};
}
