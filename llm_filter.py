import os
import re
import json
from tqdm import tqdm
from openai import OpenAI


PPFILTER_SYSPROMPT = """You are an expert academic researcher and library scientist. Your task is to classify whether a given research paper belongs to a specific Target Topic/Domain based on its Title, Venue, Year, and Abstract.

### Classification Criteria
Please evaluate the relevance using the following strict scale:

* **1 (Relevant):** The paper explicitly addresses, contributes to, or heavily relies on the Target Topic. The abstract discusses core concepts, methods, or applications directly related to the topic.
* **0 (Unsure/insufficient Info):** The abstract is ambiguous, the connection to the topic is extremely tangential, or the paper sits on the boundary. The provided information is not enough to make a definitive "Yes" or "No".
* **-1 (Irrelevant):** The paper belongs to a completely different field, or uses the keywords in a context unrelated to the Target Topic (e.g., "Apple" as a fruit vs. "Apple" as a tech company).

### Steps for Analysis
1.  **Analyze the Target Topic:** Understand the semantic meaning of the provided keywords or description.
2.  **Analyze the Paper:** Read the Title and Abstract. Check the Venue (Conference/Journal) for context (e.g., a CVPR paper is likely about Computer Vision).
3.  **Determine Relevance:** Look for semantic alignment, not just keyword matching.
4.  **Formulate Output:** Generate a brief analysis and the final numeric result.

### Output Format
You must output the result strictly in the following format (do not use Markdown code blocks, just plain text):

Analysis: [Your brief reasoning here, explaining why it fits or doesn't fit within 1-3 sentences.]
Result: [Output only one number: -1, 0, or 1]
"""

PPFILTER_USRPROMPT = """### Target Topic/Domain Description
{{topic_description}}

### Paper Information
**Title:** {{paper_title}}
**Venue & Year:** {{paper_venue}}, {{paper_year}}
**Abstract:**
{{paper_abstract}}

---
Based on the instructions, please provide the Analysis and Result.
"""


def extract_conclusion(llm_output: str):
    if not llm_output or not isinstance(llm_output, str):
        return None

    # result     -> 匹配 "result" (配合 IGNORECASE 忽略大小写)
    # \s* -> 允许 "Result" 后有任意空格
    # [:：]?     -> 允许英文冒号、中文冒号或没有冒号
    # \s* -> 允许冒号后有空格
    # (?:\*\*|'|`)* -> 非捕获组，允许数字被 Markdown 符号包裹 (如 **1**, '1', `1`)
    # (-?1|0)    -> 核心捕获组：匹配 -1, 1 或 0
    # (?:\*\*|'|`)* -> 允许尾部有 Markdown 符号
    # \b         -> 单词边界，防止匹配到 10, 01 等数字
    pattern = r"result\s*[:：]?\s*(?:\*\*|'|`)*(-?1|0)(?:\*\*|'|`)*\b"

    matches = re.findall(pattern, llm_output, re.IGNORECASE)

    if matches:
        try:
            val = int(matches[-1])
            if val in {-1, 0, 1}:
                return val
        except ValueError:
            return None
            
    return None


def extract_papers_of_topic(replies: list[dict], out_path: str):
    flag = True
    approved_topics = set()

    while flag:
        try:
            approved_topics = input("Save only the results with negative (-1), unknown (0) and/or positive (1) topic? n/<-1,0,1 (sep with comma)>:\n")
            if approved_topics.lower() == 'n':
                return
            
            approved_topics = [int(v) for v in approved_topics.strip().replace(' ', '').split(',')]
            approved_topics = set(approved_topics)
            assert -1 in approved_topics or 0 in approved_topics or 1 in approved_topics
            flag = False
        
        except Exception as e:
            print(f"Problems in input:\n{e}")
            flag = True

    replies_of_topic = []
    for r in replies:
        topic_result = r.get("is_of_topic", None)
        if topic_result is None:
            continue
        if topic_result in approved_topics:
            replies_of_topic.append(r)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(replies_of_topic, ensure_ascii=False, indent=4))
    print(f"Results with approved topics saved to {out_path}")


def main():
    import argparse
    from datetime import datetime

    run_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    parser = argparse.ArgumentParser()
    parser.add_argument("-k", "--apikey", type=str, default=None, help="If omitted, use environment variable PPSCRAP_APIKEY")
    parser.add_argument("-m", "--model_type", type=str, default="deepseek")
    parser.add_argument("-c", "--conf", type=str, default=None)
    parser.add_argument("-y", "--year", type=str, default=2025)
    parser.add_argument("-i", "--input", type=str, default=None, help="Paper list exported by scrap.py")
    parser.add_argument("-o", "--output", type=str, default=None)

    parser.add_argument("--only_filter_topic", type=str, default=None, help="If this provided, any other args will be omitted. Provide a file path for detailedly filtered papers by LLM (the .json file that contains `is_of_topic` field)")

    args = parser.parse_args()

    if not args.only_filter_topic:
        if args.conf is None:
            print("Provide `-c` or `--conf` param. Details see `--help`")
        if args.input is None:
            print("Provide `-i` or `--input` param. Details see `--help`")
        
        ## Prepare model args and model client
        base_url = None
        model_id = None

        if "deepseek" in args.model_type.lower():
            base_url = "https://api.deepseek.com"
            model_id = "deepseek-chat"    
        else:
            raise NotImplementedError(f"Model type {args.model_type} not implemented yet")
        
        client = OpenAI(
            api_key=os.environ.get('PPSCRAP_APIKEY', "") if args.apikey is None else args.apikey,
            base_url=base_url
        )
        
        ## Prepare prompt input
        topic_desc = ""
        while topic_desc == "":
            topic_desc = input("Topic description (field/subfield keywords or a line of comment):\n")

        with open(args.input, mode='r', encoding='utf-8') as f:
            ppinfo_list = json.loads(f.read())
        
        continue_cmd = input(f"Successfully read {len(ppinfo_list)} entries. Continue? [y]/n")
        if continue_cmd.lower() == 'n':
            return
        
        output = args.output
        if output is None:
            output = f"detailed_filterd_papers_{args.conf}_{args.year}_{run_time}.json"
        output_jsonl = output + 'l'
        
        replies = [{"topic_desc": topic_desc, "venue": args.conf, "year": args.year}]
        for ppinfo in tqdm(ppinfo_list, desc="Checking paper", total=len(ppinfo_list)):
            ppfilter_user = (PPFILTER_USRPROMPT
                .replace("{{topic_description}}", topic_desc)
                .replace("{{paper_title}}", ppinfo['title'])
                .replace("{{paper_venue}}", str(args.conf))
                .replace("{{paper_year}}", str(args.year))
                .replace("{{paper_abstract}}", ppinfo['abstract'])
            )

            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": PPFILTER_SYSPROMPT},
                    {"role": "user", "content": ppfilter_user},
                ],
                stream=False
            )

            reply = response.choices[0].message.content

            reply_dict = {
                "paper_title": ppinfo['title'],
                "paper_abstract": ppinfo['abstract'],
                "is_of_topic": extract_conclusion(reply),
                "llm_analysis": reply,
            }
            replies.append(reply_dict)

            with open(output_jsonl, mode=("a" if os.path.exists(output_jsonl) else "w"), encoding='utf-8') as f:
                f.write(json.dumps(reply_dict, ensure_ascii=False) + "\n")
        
        with open(output, 'w', encoding='utf-8') as f:
            f.write(json.dumps(replies, ensure_ascii=False, indent=4))
        if os.path.exists(output):
            os.remove(output_jsonl)
        print(f"Final result saved to {output}")

        ## Keep only results for...
        output_approved_topics = f"papers_to_read_{args.conf}_{args.year}_{run_time}.json"
        extract_papers_of_topic(replies, output_approved_topics)
    
    else:
        with open(args.only_filter_topic, 'r', encoding='utf-8') as f:
            replies = json.loads(f.read())
        extract_papers_of_topic(replies, f"papers_to_read_{run_time}.json")


if __name__ == "__main__":
    main()
